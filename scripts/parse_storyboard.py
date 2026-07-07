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


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    for scene in storyboard["scenes"]:
        scene.setdefault("voiceText", "")
        scene.setdefault("duration", None)
        auto_generate_single_element(scene)

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
    parser.add_argument("--image-style", default="whiteboard", choices=["whiteboard", "blackboard", "notebook"])
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
        args.output = str(_PROJECT_ROOT / "output" / f"{topic}" / "storyboard.json")

    parse_storyboard(args.input, args.output, args.image_style, args.draw_mode, args.fps, args.mode)
