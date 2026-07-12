#!/usr/bin/env python3
"""
parse_storyboard.py - Parse natural language script → storyboard.json.

If a scene has no 'elements' defined, auto-generate a single full-canvas element.
Outputs the validated storyboard.json to the output directory.
"""

import json
import os
import sys
from pathlib import Path

from config import PROJECT_ROOT, get_image_filename


def auto_generate_single_element(scene: dict, img_w: int = 1920, img_h: int = 1080) -> dict:
    """For scenes without elements, generate a single full-canvas element."""
    if scene.get("elements") is None or len(scene["elements"]) == 0:
        scene["elements"] = [{
            "id": "full",
            "description": "Full canvas content",
            "bbox": {"x": 0, "y": 0, "w": img_w, "h": img_h},
            "drawAt": None,
            "narration": scene.get("voiceText", "")
        }]
        print(f"  Auto-generated full-canvas element for scene '{scene.get('id', '?')}'")
    return scene


DRAW_STRATEGY_PROMPT = """你是白板手绘视频的动画导演。

给定一个画面元素的描述，请判断最适合的绘画顺序策略。

可选策略：
- spatial_walk: 从左上开始，按空间邻近顺序画。适合没有明确结构的通用元素。
- top_down: 从上往下画。适合人物（先头后身体）、悬挂物、下拉菜单。
- bottom_up: 从下往上画。适合金字塔、建筑、层级结构、堆叠图。
- left_right: 从左到右画。适合时间线、流程图、进度条、对比图。
- outline_first: 先画外轮廓再画内部细节。适合封闭图形（圆形图标、方框图表）。
- center_out: 从中心向外画。适合放射性图形、大脑、太阳、爆炸效果。

元素描述: {description}

只返回策略名称，不要解释。"""


def enrich_draw_strategies(scenes: list[dict]):
    """为缺少 drawStrategy 的元素自动生成。"""
    try:
        from llm_client import call_deepseek
    except (ImportError, RuntimeError):
        return  # 无 LLM 时跳过，extract_drawing_paths 会用默认 spatial_walk

    valid = {"spatial_walk", "top_down", "bottom_up",
             "left_right", "outline_first", "center_out"}

    for scene in scenes:
        for elem in scene.get("elements", []):
            if elem.get("drawStrategy"):
                continue  # 用户已指定，跳过

            desc = elem.get("description", elem.get("id", ""))
            if not desc:
                continue

            try:
                response = call_deepseek(
                    DRAW_STRATEGY_PROMPT.replace("{description}", desc),
                    temperature=0.1, max_tokens=20,
                )
                strategy = response.strip().lower().replace('"', '').replace("'", "")
                elem["drawStrategy"] = strategy if strategy in valid else "spatial_walk"
                print(f"    drawStrategy: {elem['id']} → {elem['drawStrategy']}")
            except Exception:
                elem["drawStrategy"] = "spatial_walk"


def parse_storyboard(input_path: str, output_path: str = None, image_style: str = "whiteboard",
                     draw_mode: str = "sketch_first", fps: int = 30,
                     pipeline_mode: str = "video_first") -> dict:
    """Parse a storyboard script or JSON into validated storyboard."""

    # Load input
    with open(input_path, "r", encoding="utf-8") as f:
        raw = f.read()

    # Try JSON first
    try:
        storyboard = json.loads(raw)
        print(f"Loaded storyboard JSON: {storyboard.get('meta', {}).get('title', 'untitled')}")
    except json.JSONDecodeError:
        print("ERROR: Input must be valid JSON (natural language parsing not yet implemented)")
        print("Please provide a storyboard.json file directly.")
        sys.exit(1)

    # Ensure meta section
    if "meta" not in storyboard:
        storyboard["meta"] = {}
    meta = storyboard["meta"]
    meta.setdefault("title", "Untitled")
    meta.setdefault("topic", meta["title"].lower().replace(" ", "-"))
    meta.setdefault("fps", fps)
    meta.setdefault("width", 1920)
    meta.setdefault("height", 1080)
    meta.setdefault("imageStyle", image_style)
    meta.setdefault("style", "ipad_sketch")  # 新默认画风：iPad 简笔画
    meta.setdefault("styleGuide", None)  # LLM 生成后回写
    meta.setdefault("imageAspectRatio", "16:9")
    meta.setdefault("drawMode", draw_mode)
    meta.setdefault("pipeline", {"mode": pipeline_mode, "defaultSceneDuration": None})
    meta.setdefault("camera", {"enabled": True, "maxZoom": 2.5, "transitionMs": 800})
    meta.setdefault("tts", {"provider": "tencent", "voice": 602005, "speed": 1.1})
    meta.setdefault("subtitle", {"enabled": True, "fontSize": 36})
    meta.setdefault("transition", {"type": "fade", "durationFrames": 15})
    meta.setdefault("animationEngine", "whiteboard")

    # Ensure scenes
    if "scenes" not in storyboard or not storyboard["scenes"]:
        print("ERROR: storyboard must have at least one scene")
        sys.exit(1)

    # Process each scene - auto-generate elements if missing
    for i, scene in enumerate(storyboard["scenes"]):
        scene.setdefault("voiceText", "")
        scene.setdefault("duration", None)
        # 新增 imageName 字段
        scene_id = scene.get("id", f"scene{i+1}")
        scene.setdefault("imageName", get_image_filename(scene_id))
        auto_generate_single_element(scene)

    # 自动为元素生成 drawStrategy
    enrich_draw_strategies(storyboard["scenes"])

    # Write output
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(storyboard, f, ensure_ascii=False, indent=2)
        print(f"  Wrote: {output_path}")

    return storyboard


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Parse storyboard script → storyboard.json")
    parser.add_argument("input", help="Input storyboard.json file")
    parser.add_argument("--output", "-o", help="Output path (default: output/{topic}/storyboard.json)")
    parser.add_argument("--image-style", default="refined_illustration",
                        choices=["whiteboard", "blackboard", "notebook", "refined_illustration", "custom"])
    parser.add_argument("--draw-mode", default="sketch_first", choices=["sketch_first", "sequential"])
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--mode", default="video_first", choices=["video_first", "full"])
    args = parser.parse_args()

    if not args.output:
        topic = "untitled"
        try:
            with open(args.input) as f:
                data = json.load(f)
                topic = data.get("meta", {}).get("topic", "untitled")
        except Exception:
            pass
        args.output = str(PROJECT_ROOT / "output" / f"{topic}" / "storyboard.json")

    parse_storyboard(args.input, args.output, args.image_style, args.draw_mode, args.fps, args.mode)
