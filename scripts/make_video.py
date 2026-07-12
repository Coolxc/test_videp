#!/usr/bin/env python3
"""
make_video.py - V2 白板视频管线主入口。

基于 Refactor 08 的完整重构流程，核心变化：
  - 输入支持 .md（Markdown 脚本）和 .json（storyboard 兼容）
  - Markdown → LLM 解析 → storyboard 骨架（无 bbox）
  - Vision LLM 检测元素 bbox + 推断绘制顺序
  - 双层路径：骨架（蒙版揭示）+ 轮廓（笔尖跟踪）
  - 后画动画：9 种 Transform 动画
  - PenWipe 马克笔转场
  - --review 模式：bbox 标注预览图

新流程：
  Step 1:  validate
  Step 2:  parse_script (Markdown → storyboard-skeleton.json / JSON 兼容)
  Step 3:  generate_prompts (含元素布局约束)
           ── 暂停：等用户生成 PNG ──
  Step 4:  validate_images
  Step 5:  detect_elements (Vision bbox)
           ── [--review] 可选暂停 ──
  Step 6:  tts (仅 full 模式)
  Step 7:  compute_timeline (含后画动画时间)
  Step 8:  generate_sfx
  Step 9:  extract_paths (双层路径：骨架 + 轮廓)
  Step 10: generate_subtitles
  Step 11: mix_audio (仅 full 模式)
  Step 12: deploy + render (Remotion)
  Step 13: generate_publish

Usage:
  # Step 1: Parse script + Generate prompts
  python scripts/make_video.py --input script.md --mode video-first

  # Resume after images are ready
  python scripts/make_video.py --input script.md --mode video-first --skip-prompts

  # With bbox review
  python scripts/make_video.py --input script.md --review
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from config import PROJECT_ROOT, get_output_dir

_SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def _import_step(name):
    """Dynamic import of a step module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(_SCRIPTS_DIR / f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_storyboard(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_checkpoint(output_dir: Path) -> dict:
    cp_path = output_dir / ".checkpoint.json"
    if cp_path.exists():
        with open(cp_path, "r") as f:
            return json.load(f)
    return {}


def _write_checkpoint(output_dir: Path, step: str, data: dict = None):
    cp_path = output_dir / ".checkpoint.json"
    cp = _read_checkpoint(output_dir)
    cp[step] = {"done": True, "timestamp": time.time(), "data": data or {}}
    os.makedirs(output_dir, exist_ok=True)
    with open(cp_path, "w") as f:
        json.dump(cp, f, indent=2)


def _step_done(output_dir: Path, step: str) -> bool:
    cp = _read_checkpoint(output_dir)
    return step in cp and cp[step].get("done", False)


def run_step(step_name: str, output_dir: Path, skip_if_done: bool = True, **kwargs):
    """Run a pipeline step with checkpoint resumability."""
    if skip_if_done and _step_done(output_dir, step_name):
        print(f"\n[SKIP] Step '{step_name}' already completed")
        return

    print(f"\n{'='*60}")
    print(f"  Step: {step_name}")
    print(f"{'='*60}")
    os.makedirs(output_dir, exist_ok=True)
    return _write_checkpoint(output_dir, step_name)


def make_video(input_path: str, mode: str = "video_first",
               skip_prompts: bool = False, audio_only: bool = False,
               video_path: str = None, draw_mode: str = "sequential",
               no_hand: bool = False, review: bool = False):
    """Main pipeline orchestration for V2 whiteboard video."""

    # ── Input detection ──
    is_markdown = input_path.endswith(".md")

    # For markdown input, we parse it first to get storyboard for output dir
    if is_markdown:
        parse_mod = _import_step("parse_markdown_script")
        output_dir = Path(input_path).parent
        # Quick pre-read to estimate topic
        topic = "untitled"
        try:
            with open(input_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("# ") and not line.startswith("## "):
                        topic = line[2:].strip().lower().replace(" ", "-")
                        break
        except Exception:
            pass
        output_dir = PROJECT_ROOT / "output" / f"{topic}-{time.strftime('%Y%m%d')}"
        storyboard_path = str(output_dir / "storyboard-skeleton.json")
    else:
        storyboard = _load_storyboard(input_path)
        output_dir = get_output_dir(storyboard)
        storyboard_path = input_path

    os.makedirs(output_dir, exist_ok=True)

    print(f"\n{'#'*60}")
    print(f"  Whiteboard Video Pipeline V2")
    print(f"  Input: {input_path}")
    print(f"  Mode: {mode}")
    print(f"  Output: {output_dir}")
    print(f"{'#'*60}")

    # ── Audio-only mode ──
    if audio_only:
        print("\n[Audio-only mode]")
        if not video_path or not os.path.exists(video_path):
            print("ERROR: --video required for audio-only mode")
            sys.exit(1)

        if not _step_done(output_dir, "tts"):
            tts_mod = _import_step("tts_pipeline")
            tts_mod.tts_pipeline(storyboard_path, str(output_dir))

        audio_dir = output_dir / "audio"
        if not _step_done(output_dir, "mix"):
            mixer_mod = _import_step("audio_mixer")
            mixer_mod.mix_all_scenes(storyboard_path, str(audio_dir),
                                     timeline_path=str(output_dir / "timeline.json"))

        merged_path = output_dir / "video.mp4"
        print(f"\n  Merging audio into video...")
        audio_files = sorted(audio_dir.glob("*_mixed.wav"))
        if audio_files:
            concat_path = output_dir / "_audio_concat.txt"
            with open(concat_path, "w") as f:
                for af in audio_files:
                    f.write(f"file '{af.absolute()}'\n")
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path,
                "-f", "concat", "-safe", "0", "-i", str(concat_path),
                "-c:v", "copy", "-c:a", "aac", "-shortest",
                str(merged_path),
            ], check=True)
            os.remove(concat_path)
            print(f"  Output: {merged_path}")
        return

    # ── Step 0: Validate ──
    if not _step_done(output_dir, "validate"):
        val_mod = _import_step("validate")
        # For .md input, skip storyboard schema validation (not yet parsed)
        val_storyboard = storyboard_path if not is_markdown else None
        val_mod.run_checks(val_storyboard, check_tts=(mode == "full"))
        _write_checkpoint(output_dir, "validate")

    # ── Step 1: Parse script ──
    if not skip_prompts and not _step_done(output_dir, "parse"):
        if is_markdown:
            # Markdown → storyboard 骨架
            parse_mod = _import_step("parse_markdown_script")
            parse_mod.parse_markdown_script(input_path, str(output_dir))
            storyboard_path = str(output_dir / "storyboard-skeleton.json")
        else:
            # JSON 输入：走现有兼容路径
            parse_mod = _import_step("parse_storyboard")
            parse_mod.parse_storyboard(input_path, str(output_dir / "storyboard.json"),
                                       draw_mode=draw_mode, pipeline_mode=mode)
            storyboard_path = str(output_dir / "storyboard.json")
        _write_checkpoint(output_dir, "parse")

    # ── Step 2: Generate prompts ──
    if not skip_prompts and not _step_done(output_dir, "prompts"):
        storyboard = _load_storyboard(storyboard_path)
        prompts_mod = _import_step("generate_prompts")
        prompts_mod.generate_prompts(storyboard, str(output_dir), use_llm=True)
        _write_checkpoint(output_dir, "prompts")
        print(f"\n  >>> Image prompts generated: {output_dir / 'prompts.md'}")
        print(f"  >>> Generate images using your preferred tool, place in {output_dir / 'images'}/")
        print(f"  >>> Then run with --skip-prompts to continue")
        return  # Pause for user to generate images

    # ── After skip-prompts: continue from here ──

    # Ensure storyboard_path is set correctly after skip
    if is_markdown and storyboard_path == str(output_dir / "storyboard-skeleton.json"):
        # Check if skeleton exists, fallback to storyboard.json
        if not os.path.exists(storyboard_path):
            alt_path = str(output_dir / "storyboard.json")
            if os.path.exists(alt_path):
                storyboard_path = alt_path

    # ── Step 3: Validate images ──
    images_dir = output_dir / "images"
    if not _step_done(output_dir, "validate_images"):
        val_img_mod = _import_step("validate_images")
        sb_for_validation = _load_storyboard(storyboard_path)
        issues = val_img_mod.validate_images(sb_for_validation, str(images_dir))
        val_img_mod.fix_background_color(str(images_dir))
        _write_checkpoint(output_dir, "validate_images", {"issues": len(issues)})

    # ── Step 4: Detect elements (Vision bbox) ──
    if not _step_done(output_dir, "detect_elements"):
        detect_mod = _import_step("detect_elements")

        # For markdown pipeline, output storyboard-complete.json
        if is_markdown:
            complete_path = str(output_dir / "storyboard-complete.json")
            detect_mod.process_all_scenes(
                storyboard_path,
                str(images_dir),
                complete_path,
                review=review,
            )
            storyboard_path = complete_path
        else:
            # For JSON pipeline, update in-place
            detect_mod.process_all_scenes(
                storyboard_path,
                str(images_dir),
                storyboard_path,
                review=review,
            )

        _write_checkpoint(output_dir, "detect_elements")

        # --review 模式：暂停等用户确认
        if review and not _step_done(output_dir, "detect_reviewed"):
            print(f"\n  >>> Bbox 预览图已生成: {output_dir / 'preview'}/")
            print(f"  >>> 请检查各场景的 *_bbox.png 预览图")
            print(f"  >>> 确认满意后，再次运行相同命令以继续（checkpoint 已记录）")
            _write_checkpoint(output_dir, "detect_reviewed")
            return

    # ── Step 5: TTS (full mode only) ──
    tts_data = None
    if mode == "full":
        if not _step_done(output_dir, "tts"):
            tts_mod = _import_step("tts_pipeline")
            storyboard = _load_storyboard(storyboard_path)
            meta = storyboard.get("meta", {})
            tts_data = tts_mod.tts_pipeline(
                storyboard_path, str(output_dir),
                provider=meta.get("tts", {}).get("provider", "tencent"),
                voice=meta.get("tts", {}).get("voice", 602005),
                speed=meta.get("tts", {}).get("speed", 1.1),
            )
            _write_checkpoint(output_dir, "tts", {"scenes": list(tts_data.keys())})
        else:
            cp = _read_checkpoint(output_dir)
            tts_data = cp.get("tts", {}).get("data", {})

    # ── Step 6: Compute timeline (含后画动画时间) ──
    timeline_path = output_dir / "timeline.json"
    if not _step_done(output_dir, "timeline"):
        timeline_mod = _import_step("compute_timeline")
        storyboard = _load_storyboard(storyboard_path)
        fps = storyboard.get("meta", {}).get("fps", 30)
        timeline = timeline_mod.compute_timeline(
            storyboard_path, str(timeline_path),
            tts_data=tts_data, draw_mode="sequential",
            transition_ms=800, fps=fps,
        )
        _write_checkpoint(output_dir, "timeline", {"totalFrames": timeline["totalFrames"]})
    else:
        with open(timeline_path, encoding="utf-8") as f:
            timeline = json.load(f)

    # ── Step 7: Generate default SFX ──
    if not _step_done(output_dir, "sfx"):
        sfx_mod = _import_step("generate_default_sfx")
        sfx_mod.generate_sfx()
        _write_checkpoint(output_dir, "sfx")

    # ── Step 8: Extract drawing paths (双层路径：骨架 + 轮廓) ──
    if not _step_done(output_dir, "drawing_paths"):
        paths_mod = _import_step("extract_drawing_paths")
        # 使用双层路径提取
        try:
            paths_mod.extract_all_scenes_dual(
                storyboard_path,
                str(images_dir),
                str(output_dir),
            )
        except Exception as e:
            print(f"  [WARN] 双层路径提取失败 ({e})，回退到仅骨架路径")
            paths_mod.extract_all_scenes(
                storyboard_path,
                str(images_dir),
                str(output_dir),
            )
        _write_checkpoint(output_dir, "drawing_paths")

    # ── Step 9: Generate subtitles ──
    subs_path = output_dir / "subtitles.srt"
    if not _step_done(output_dir, "subtitles"):
        with open(timeline_path, encoding="utf-8") as f:
            timeline = json.load(f)
        storyboard = _load_storyboard(storyboard_path)
        subs_mod = _import_step("generate_subtitles")
        subs_mod.generate_srt(timeline, storyboard, str(subs_path))
        _write_checkpoint(output_dir, "subtitles")

    # ── Step 10: Mix audio (full mode only) ──
    if mode == "full":
        if not _step_done(output_dir, "mix"):
            mixer_mod = _import_step("audio_mixer")
            mixer_mod.mix_all_scenes(
                storyboard_path, str(output_dir / "audio"),
                timeline_path=str(timeline_path),
                output_dir=str(output_dir),
            )
            _write_checkpoint(output_dir, "mix")

    # ── Step 11: Deploy resources + Remotion render ──
    video_output = output_dir / ("video.mp4" if mode == "full" else "video_silent.mp4")
    if not _step_done(output_dir, "remotion"):
        # Deploy resources
        deploy_mod = _import_step("deploy_resources")
        deploy_mod.deploy_resources(
            storyboard_path, str(output_dir),
            copy_animations=False,
            copy_audio=(mode == "full"),
            timeline_path=str(timeline_path),
            mode=mode,
        )

        # Remotion render
        remotion_dir = PROJECT_ROOT / "remotion-project"
        os.makedirs(str(video_output.parent), exist_ok=True)
        print(f"\n  Rendering with Remotion...")
        print(f"  Output: {video_output}")
        npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
        output_name = video_output.name
        result = subprocess.run(
            [npx_cmd, "remotion", "render", "src/index.tsx", "VideoMain",
             "--output", output_name, "--overwrite"],
            cwd=str(remotion_dir),
            capture_output=True, text=True,
        )
        print(result.stdout)
        if result.returncode == 0:
            rendered = remotion_dir / output_name
            if rendered.exists():
                shutil.move(str(rendered), str(video_output))
                size_mb = os.path.getsize(video_output) / (1024 * 1024)
                print(f"  Remotion render complete: {video_output} ({size_mb:.1f} MB)")
                _write_checkpoint(output_dir, "remotion")
            else:
                print(f"  [WARN] Render returned success but file not found")
                import glob as _glob
                recent = sorted(_glob.glob(str(remotion_dir / "**/*.mp4"), recursive=True),
                              key=os.path.getmtime, reverse=True)[:3]
                if recent:
                    for f in recent:
                        print(f"    Found: {f}")
                    shutil.copy2(recent[0], str(video_output))
                    print(f"  Copied to: {video_output}")
                    _write_checkpoint(output_dir, "remotion")
                else:
                    print(f"  [ERR] No MP4 found")
        else:
            print(f"  [ERR] Remotion render failed:")
            print(result.stderr)

    # ── Step 12: Generate publish copy ──
    if not _step_done(output_dir, "publish"):
        pub_mod = _import_step("generate_publish")
        pub_mod.generate_publish(storyboard_path, str(output_dir / "publish.md"))
        _write_checkpoint(output_dir, "publish")

    print(f"\n{'='*60}")
    print(f"  Pipeline complete!")
    print(f"  Output: {output_dir}")
    if video_output.exists():
        size_mb = os.path.getsize(video_output) / (1024 * 1024)
        print(f"  Video: {video_output.name} ({size_mb:.1f} MB)")
    print(f"{'='*60}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="V2 whiteboard video pipeline orchestrator")
    parser.add_argument("--input", "-i", required=True,
                        help="Input (.md script or .json storyboard)")
    parser.add_argument("--mode", default="video_first", choices=["video_first", "full"],
                        help="Pipeline mode")
    parser.add_argument("--skip-prompts", action="store_true",
                        help="Skip prompt generation (continue after images are ready)")
    parser.add_argument("--audio-only", action="store_true",
                        help="Only add audio to existing video")
    parser.add_argument("--video", help="Path to existing video (for audio-only mode)")
    parser.add_argument("--draw-mode", default="sequential",
                        choices=["sequential"],
                        help="Draw mode")
    parser.add_argument("--no-hand", action="store_true", help="Disable drawing hand")
    parser.add_argument("--review", action="store_true",
                        help="Pause after bbox detection to review annotations")
    args = parser.parse_args()

    make_video(
        input_path=args.input,
        mode=args.mode,
        skip_prompts=args.skip_prompts,
        audio_only=args.audio_only,
        video_path=args.video,
        draw_mode=args.draw_mode,
        no_hand=args.no_hand,
        review=args.review,
    )


if __name__ == "__main__":
    main()
