#!/usr/bin/env python3
"""
compute_timeline.py - SVG 路径动画方案的简化时间轴计算。

每个元素只有一组时间：drawAtFrame + drawDurationFrames（不再区分 sketch/colorize）。
直接 30fps 输出，与 Remotion 一致。

输出 timeline.json 格式：
{
  "fps": 30,
  "totalFrames": 450,
  "transitionDurationFrames": 25,
  "drawMode": "sequential",
  "scenes": [
    {
      "id": "scene1",
      "startFrame": 0,
      "durationFrames": 210,
      "elements": [
        { "id": "person", "drawAtFrame": 0, "drawDurationFrames": 90, "narration": "..." },
      ]
    }
  ]
}
"""

import json
import os
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 时间常量 ──
FRAME_RATE = 30
ELEMENT_GAP_FRAMES = 10           # 元素间停顿（~0.33s），画手抬起移位
HOLD_FRAMES = 45                   # 场景末尾 hold 静态画面（~1.5s）
TRANSITION_FRAMES = 25             # 转场帧数（~0.83s），被下一场景的白纸覆盖
ANIMATION_DELAY_FRAMES = 15        # 元素画完后到动画开始的延迟（~0.5s）
ANIMATION_FREEZE_MARGIN = 15       # 转场前动画冻结余量（~0.5s）
MIN_ELEMENT_DRAW_FRAMES = 30       # 单元素最小绘制帧数（~1.0s）
CHARS_PER_SECOND = 4.0             # 中文旁白语速
NARRATION_MARGIN = 1.2             # 旁白时长余量系数
MIN_SCENE_FRAMES = FRAME_RATE * 5  # 场景最短 5 秒


def estimate_scene_duration_frames(scene: dict) -> int:
    """
    估算场景总帧数（含间隙、hold、转场）。

    基于旁白字数估算，同时满足元素数量的最小时长要求。
    """
    elements = scene.get("elements", [])
    n = max(1, len(elements))

    # 基于旁白的时长
    total_chars = sum(len(e.get("narration", "")) for e in elements)
    narration_frames = round(total_chars / CHARS_PER_SECOND * NARRATION_MARGIN * FRAME_RATE)

    # 基于元素数量的最小时长
    min_draw_frames = n * MIN_ELEMENT_DRAW_FRAMES

    # 取较大值
    draw_frames = max(min_draw_frames, narration_frames)

    # 加上间隙 + hold + 转场
    gap_frames = (n - 1) * ELEMENT_GAP_FRAMES
    total = draw_frames + gap_frames + HOLD_FRAMES + TRANSITION_FRAMES

    return max(total, MIN_SCENE_FRAMES)


def allocate_element_durations(elements: list[dict], total_draw_frames: int) -> list[int]:
    """
    按旁白字数比例分配元素绘制帧数。

    Args:
        elements: 元素列表
        total_draw_frames: 可用于绘制的总帧数

    Returns:
        每个元素的绘制帧数列表
    """
    total_chars = sum(len(e.get("narration", "")) for e in elements) or len(elements)

    durations = []
    for elem in elements:
        chars = len(elem.get("narration", "")) or 1
        frames = max(MIN_ELEMENT_DRAW_FRAMES, round(total_draw_frames * chars / total_chars))
        durations.append(frames)

    return durations


def compute_timeline_entry(
    scene: dict,
    scene_start_frame: int,
    tts_segments: list[dict] | None = None,
    fps: int = 30,
    draw_delay: int = 0,
) -> dict:
    """
    计算单个场景的时间轴条目。

    Returns:
        {
            "id": str,
            "startFrame": int,       # global frame
            "durationFrames": int,
            "elements": [{
                "id": str,
                "drawAtFrame": int,          # scene-relative
                "drawDurationFrames": int,
                "narration": str,
            }]
        }
    """
    elements = scene.get("elements", [])
    n = len(elements)

    # 场景总帧数
    total_frames = estimate_scene_duration_frames(scene)

    # 可用于绘制的帧数（去掉间隙、hold、转场）
    gap_frames_total = (n - 1) * ELEMENT_GAP_FRAMES
    draw_budget = total_frames - gap_frames_total - HOLD_FRAMES - TRANSITION_FRAMES

    # 分配元素绘制时长
    elem_draw_frames = allocate_element_durations(elements, draw_budget)

    # 编排时间轴
    timeline_elements = []
    current_frame = draw_delay
    for i, elem in enumerate(elements):
        draw_duration = elem_draw_frames[i]
        draw_end_frame = current_frame + draw_duration

        # 后画动画时间
        post_anim = elem.get("postAnimation")
        if post_anim:
            anim_start = draw_end_frame + ANIMATION_DELAY_FRAMES
            anim_freeze = total_frames - TRANSITION_FRAMES - ANIMATION_FREEZE_MARGIN
        else:
            anim_start = None
            anim_freeze = None

        timeline_elements.append({
            "id": elem["id"],
            "drawAtFrame": current_frame,
            "drawDurationFrames": draw_duration,
            "narration": elem.get("narration", ""),
            "postAnimation": post_anim,
            "animationStartFrame": anim_start,
            "animationFreezeFrame": anim_freeze,
        })
        current_frame += draw_duration
        if i < n - 1:
            current_frame += ELEMENT_GAP_FRAMES

    return {
        "id": scene["id"],
        "startFrame": scene_start_frame,
        "durationFrames": total_frames,
        "elements": timeline_elements,
    }


def compute_timeline(
    storyboard_path: str,
    output_path: str | None = None,
    tts_data: dict | None = None,
    draw_mode: str = "sequential",
    transition_ms: int = 800,
    fps: int = 30,
) -> dict:
    """完整的时间轴计算（所有场景）。"""
    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    meta = storyboard.get("meta", {})
    scenes = storyboard.get("scenes", [])

    scene_entries = []
    current_frame = 0

    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        tts_segments = None
        if tts_data and scene_id in tts_data:
            tts_segments = tts_data[scene_id].get("segments")

        delay = TRANSITION_FRAMES if i > 0 else 0
        entry = compute_timeline_entry(
            scene,
            current_frame,
            tts_segments=tts_segments,
            fps=fps,
            draw_delay=delay,
        )
        scene_entries.append(entry)

        # 下一个场景开始帧 = 当前场景开始 + 时长 - 重叠帧数
        current_frame += entry["durationFrames"]
        if i < len(scenes) - 1:
            current_frame -= TRANSITION_FRAMES  # 重叠转场

    timeline = {
        "fps": fps,
        "totalFrames": current_frame,
        "transitionDurationFrames": TRANSITION_FRAMES,
        "drawMode": "sequential",
        "scenes": scene_entries,
    }

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
        print(f"  Timeline: {output_path} ({current_frame} frames total)")

    return timeline


def finalize_timeline_with_ffprobe(
    timeline_path: str,
    anim_dir: str,
    output_path: str | None = None,
):
    """
    SVG 方案不再需要 ffprobe 校正。
    此函数保留为空兼容，只是重写 timeline 文件。
    """
    print("  [SKIP] ffprobe finalization not needed for SVG pipeline")
    if output_path and output_path != timeline_path:
        import shutil
        shutil.copy2(timeline_path, output_path)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Compute SVG animation timeline")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--output", "-o", help="Output timeline.json path")
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    with open(args.storyboard, encoding="utf-8") as f:
        sb = json.load(f)
    topic = sb.get("meta", {}).get("topic", "untitled")

    output = args.output or str(_PROJECT_ROOT / "output" / topic / "timeline.json")

    compute_timeline(args.storyboard, output, fps=args.fps)
