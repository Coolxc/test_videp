#!/usr/bin/env python3
"""
generate_animations.py - Batch generate whiteboard animations for all scenes.

Reads storyboard.json + regions_detected.json to generate per-scene MP4 files.
Handles background color normalization and scene_final.mp4 naming.
"""

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

from generate_scene_animation import generate_scene_with_regions, BACKGROUND_BGR


def normalize_background(image_path: str):
    """Replace near-white/beige background pixels with exact #F6F1E3."""
    img = cv2.imread(image_path)
    if img is None:
        return

    mask = cv2.inRange(img, (200, 210, 220), (255, 255, 255))
    if mask.sum() > 0:
        img[mask > 0] = np.array([227, 241, 246], dtype=np.uint8)  # BGR
        cv2.imwrite(image_path, img)
        return True
    return False


def generate_animations(storyboard_path: str, regions_path: str = None,
                         output_dir: str = None, camera_config: dict = None,
                         draw_hand: bool = True, draw_mode: str = "sketch_first"):
    """Batch generate animations for all scenes."""

    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    # Load regions (if available)
    regions_data = {}
    if regions_path and os.path.exists(regions_path):
        with open(regions_path, "r", encoding="utf-8") as f:
            regions_data_raw = json.load(f)
        # regions_data_raw is likely a dict of scene_id -> regions list
        if isinstance(regions_data_raw, dict):
            regions_data = regions_data_raw
        else:
            print("  [WARN] regions file format unexpected, skipping")

    meta = storyboard.get("meta", {})
    scenes = storyboard.get("scenes", [])

    if camera_config is None:
        camera_config = meta.get("camera", {"enabled": True, "maxZoom": 2.5, "transitionMs": 800})

    topic = meta.get("topic", "untitled")
    images_dir = os.path.join(output_dir or str(_PROJECT_ROOT / "output" / topic), "images")
    anim_dir = os.path.join(output_dir or str(_PROJECT_ROOT / "output" / topic), "animations")
    os.makedirs(anim_dir, exist_ok=True)

    results = {}

    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        img_path = os.path.join(images_dir, f"{scene_id}.png")
        if not os.path.exists(img_path):
            img_path = os.path.join(images_dir, f"{scene_id}.jpg")
        if not os.path.exists(img_path):
            print(f"  [SKIP] Scene '{scene_id}': no image found")
            continue

        # Normalize background
        normalize_background(img_path)
        print(f"\n[{i+1}/{len(scenes)}] Animating: {scene_id}")

        # Get regions for this scene
        scene_regions = scene.get("elements", [])
        if not scene_regions:
            # Full canvas single element
            img = cv2.imread(img_path)
            if img is not None:
                h, w = img.shape[:2]
                scene_regions = [{
                    "id": "full",
                    "bbox": {"x": 0, "y": 0, "w": w, "h": h},
                    "drawAt": 0,
                    "durationMs": 3000,
                    "narration": scene.get("voiceText", ""),
                }]

        # Calculate total duration
        total_duration_ms = scene.get("totalDurationMs", 0)
        if total_duration_ms <= 0:
            # Estimate: sum of element durations + transitions + blend/hold
            total_anim_ms = sum(
                r.get("durationMs", 3000) for r in scene_regions
            )
            n = len(scene_regions)
            transition_ms = camera_config.get("transitionMs", 800)
            if draw_mode == "sketch_first" and n > 1:
                total_transition_ms = ((n - 1) * 2 + 1.5) * transition_ms
            else:
                total_transition_ms = (n - 1) * transition_ms
            total_duration_ms = total_anim_ms + int(total_transition_ms) + 1500 + 1500

        region_list = []
        for j, elem in enumerate(scene_regions):
            region_list.append({
                "id": elem.get("id", f"elem_{j}"),
                "bbox": elem.get("bbox", {"x": 0, "y": 0, "w": 1920, "h": 1080}),
                "drawAt": elem.get("drawAt", 0),
                "durationMs": elem.get("durationMs", 3000),
                "narration": elem.get("narration", ""),
            })

        # Generate animation
        output_path = generate_scene_with_regions(
            image_path=img_path,
            regions=region_list,
            total_duration_ms=total_duration_ms,
            output_dir=anim_dir,
            camera_config=camera_config,
            draw_hand=draw_hand,
            draw_mode=draw_mode,
        )

        # Rename to scene-specific name
        scene_final = os.path.join(anim_dir, f"{scene_id}_final.mp4")
        generated = os.path.join(anim_dir, "scene_final.mp4")
        if os.path.exists(generated):
            if os.path.exists(scene_final):
                os.remove(scene_final)
            os.rename(generated, scene_final)
            results[scene_id] = scene_final
            print(f"  -> {scene_final}")
        elif output_path and os.path.exists(output_path):
            results[scene_id] = output_path

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batch generate whiteboard animations")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--regions", help="Path to regions_detected.json")
    parser.add_argument("--output-dir", "-o", help="Output directory")
    parser.add_argument("--no-hand", action="store_true", help="Disable drawing hand")
    parser.add_argument("--draw-mode", default="sketch_first", choices=["sketch_first", "sequential"])
    args = parser.parse_args()

    generate_animations(
        args.storyboard,
        regions_path=args.regions,
        output_dir=args.output_dir,
        draw_hand=not args.no_hand,
        draw_mode=args.draw_mode,
    )
