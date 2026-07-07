#!/usr/bin/env python3
"""
validate_images.py - Validate generated images for completeness, size, background color,
and cross-scene style consistency via histogram comparison.
"""

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKGROUND_BGR = np.array([227, 241, 246], dtype=np.uint8)  # #F6F1E3


def validate_images(storyboard: dict, images_dir: str) -> list[str]:
    """Validate all scene images. Returns list of (error/warning) messages."""
    messages = []
    scenes = storyboard.get("scenes", [])
    meta = storyboard.get("meta", {})

    expected_w = meta.get("width", 1920)
    expected_h = meta.get("height", 1080)

    histograms = []

    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        img_path = os.path.join(images_dir, f"{scene_id}.png")

        # 1. Check file exists
        if not os.path.exists(img_path):
            # Try jpg
            img_path = os.path.join(images_dir, f"{scene_id}.jpg")
            if not os.path.exists(img_path):
                messages.append(f"[ERR] Scene '{scene_id}': image not found ({scene_id}.png/.jpg)")
                continue

        # Read image
        img = cv2.imread(img_path)
        if img is None:
            messages.append(f"[ERR] Scene '{scene_id}': cannot read image")
            continue

        h, w = img.shape[:2]

        # 2. Check size
        min_dim = min(w, h)
        if min_dim < 512:
            messages.append(f"[WARN] Scene '{scene_id}': image too small ({w}x{h}, min 512px recommended)")

        # 3. Check background color (near-white/beige)
        corner_pixels = [
            img[5, 5], img[5, -5], img[-5, 5], img[-5, -5],
            img[h//2, 5], img[h//2, -5],
        ]
        avg_corner = np.mean(corner_pixels, axis=0)
        is_light = np.all(avg_corner > 150)
        if not is_light:
            messages.append(f"[WARN] Scene '{scene_id}': background may not be light enough "
                            f"(avg corner BGR: {avg_corner.astype(int)})")

        # 4. Compute histogram for cross-scene consistency
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
        hist = cv2.normalize(hist, hist).flatten()
        histograms.append((scene_id, hist))

        print(f"  Scene '{scene_id}': {w}x{h}, OK")

    # 5. Cross-scene histogram comparison
    if len(histograms) >= 2:
        print("\n  Cross-scene style consistency check...")
        for i in range(len(histograms)):
            for j in range(i + 1, len(histograms)):
                sim = cv2.compareHist(histograms[i][1], histograms[j][1], cv2.HISTCMP_CORREL)
                if sim < 0.8:
                    messages.append(f"[WARN] Scene '{histograms[i][0]}' vs '{histograms[j][0]}': "
                                    f"histogram correlation={sim:.3f} (< 0.8, possible style mismatch)")

    # Summary
    if messages:
        print(f"\n  Validation complete: {len(messages)} issue(s)")
        for msg in messages:
            print(f"    {msg}")
    else:
        print(f"\n  All images validated OK!")

    return messages


def fix_background_color(images_dir: str, backup: bool = True):
    """Fix near-white background pixels to exact #F6F1E3."""
    import glob
    for img_path in glob.glob(os.path.join(images_dir, "*.png")) + glob.glob(os.path.join(images_dir, "*.jpg")):
        img = cv2.imread(img_path)
        if img is None:
            continue

        # Near-white/beige → exact background color
        mask = cv2.inRange(img, (200, 210, 220), (255, 255, 255))
        if mask.sum() > 0:
            if backup:
                backup_path = img_path + ".bak.png"
                cv2.imwrite(backup_path, img)
            img[mask > 0] = _BACKGROUND_BGR
            cv2.imwrite(img_path, img)
            print(f"  Fixed background: {os.path.basename(img_path)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Validate scene images")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--images-dir", "-i", help="Path to images directory (default: output/{topic}/images)")
    parser.add_argument("--fix-bg", action="store_true", help="Auto-fix background colors")
    args = parser.parse_args()

    with open(args.storyboard, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    topic = storyboard.get("meta", {}).get("topic", "untitled")
    if not args.images_dir:
        args.images_dir = str(_PROJECT_ROOT / "output" / topic / "images")

    if args.fix_bg:
        fix_background_color(args.images_dir)

    validate_images(storyboard, args.images_dir)
