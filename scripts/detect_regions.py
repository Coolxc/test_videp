#!/usr/bin/env python3
"""
detect_regions.py - Automatically detect element regions in scene images.

Uses contour detection and connected components to find distinct visual elements.
Outputs regions_preview.png (annotated image) and regions_detected.json.
Results are advisory - user confirms/adjusts bbox in storyboard.json.
"""

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np


from config import PROJECT_ROOT


def detect_full_content_bbox(image_path: str, bg_color_bgr=(227, 241, 246),
                              tolerance: int = 35, margin: int = 10) -> dict:
    """检测整图中所有非背景内容的最紧包围框。
    作为 bbox 预估失败时的 fallback。
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"x": 0, "y": 0, "w": 0, "h": 0}
    h, w = img.shape[:2]

    # 用自适应阈值（与引擎一致）检测内容
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10
    )

    # 反转（内容为白色）
    content_mask = 255 - thresh

    # 也加入颜色差异检测（补充阈值方法的盲区）
    bg = np.array(bg_color_bgr, dtype=np.float32)
    diff = np.linalg.norm(img.astype(np.float32) - bg, axis=2)
    color_mask = (diff > tolerance * 3).astype(np.uint8) * 255

    # 合并两种检测
    combined = cv2.bitwise_or(content_mask, color_mask)

    # 形态学操作：去噪 + 连接
    kernel = np.ones((5, 5), np.uint8)
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)

    # 查找包围框
    coords = cv2.findNonZero(combined)
    if coords is None:
        return {"x": 0, "y": 0, "w": w, "h": h}

    x, y, bw, bh = cv2.boundingRect(coords)

    # 加 margin
    x = max(0, x - margin)
    y = max(0, y - margin)
    bw = min(w - x, bw + 2 * margin)
    bh = min(h - y, bh + 2 * margin)

    return {"x": x, "y": y, "w": bw, "h": bh}


def detect_regions(image_path: str, min_area_ratio: float = 0.01,
                   margin: int = 25, merge_distance: int = 80) -> list[dict]:
    """
    Detect distinct visual regions in an image using contour + connected components.

    Args:
        image_path: Path to the input image.
        min_area_ratio: Minimum region area as fraction of total image.
        margin: Extra padding pixels around detected bounding boxes.
        merge_distance: Merge overlapping/nearby boxes within this distance.

    Returns:
        List of {id, bbox: {x, y, w, h}} dicts.
    """
    img = cv2.imread(image_path)
    if img is None:
        print(f"ERROR: Cannot read image: {image_path}")
        return []

    h, w = img.shape[:2]
    total_area = h * w
    min_area = int(total_area * min_area_ratio)

    print(f"  Image: {w}x{h}, min_area={min_area}px")

    # Convert to grayscale and threshold
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Edge detection
    edges = cv2.Canny(gray, 30, 100)

    # Complement with adaptive threshold (same as animation engine)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10
    )
    content_mask = 255 - thresh

    # Merge Canny edges + adaptive threshold content
    combined_edges = cv2.bitwise_or(edges, content_mask)

    # Dilate to close gaps
    kernel = np.ones((5, 5), np.uint8)
    dilated = cv2.dilate(combined_edges, kernel, iterations=2)

    # Find contours
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter by area and get bounding boxes
    boxes = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)

        # Apply margin (clamp to image bounds)
        x = max(0, x - margin)
        y = max(0, y - margin)
        bw = min(w - x, bw + 2 * margin)
        bh = min(h - y, bh + 2 * margin)

        boxes.append({"x": x, "y": y, "w": bw, "h": bh})

    # Merge overlapping/nearby boxes
    merged = _merge_boxes(boxes, merge_distance)

    # Sort by position (top-left to bottom-right)
    merged.sort(key=lambda b: (b["y"], b["x"]))

    # Assign IDs
    regions = []
    for i, b in enumerate(merged):
        regions.append({
            "id": f"region_{i + 1}",
            "bbox": b,
        })

    return regions


def _merge_boxes(boxes: list[dict], merge_distance: int) -> list[dict]:
    """Merge overlapping or nearby bounding boxes."""
    if not boxes:
        return []

    merged = list(boxes)
    changed = True

    while changed:
        changed = False
        new_boxes = []

        for i, b1 in enumerate(merged):
            if b1 is None:
                continue
            for j in range(i + 1, len(merged)):
                b2 = merged[j]
                if b2 is None:
                    continue

                # Check if they overlap or are close
                if _boxes_near(b1, b2, merge_distance):
                    # Merge
                    merged_box = {
                        "x": min(b1["x"], b2["x"]),
                        "y": min(b1["y"], b2["y"]),
                        "w": max(b1["x"] + b1["w"], b2["x"] + b2["w"]) - min(b1["x"], b2["x"]),
                        "h": max(b1["y"] + b1["h"], b2["y"] + b2["h"]) - min(b1["y"], b2["y"]),
                    }
                    new_boxes.append(merged_box)
                    merged[j] = None
                    changed = True
                    break
            else:
                new_boxes.append(b1)

        merged = new_boxes

    return merged


def _boxes_near(b1: dict, b2: dict, threshold: int) -> bool:
    """Check if two boxes overlap or are within threshold distance."""
    # Check overlap
    overlap_x = max(0, min(b1["x"] + b1["w"], b2["x"] + b2["w"]) - max(b1["x"], b2["x"]))
    overlap_y = max(0, min(b1["y"] + b1["h"], b2["y"] + b2["h"]) - max(b1["y"], b2["y"]))

    if overlap_x > 0 and overlap_y > 0:
        return True

    # Check distance between box centers
    cx1, cy1 = b1["x"] + b1["w"] / 2, b1["y"] + b1["h"] / 2
    cx2, cy2 = b2["x"] + b2["w"] / 2, b2["y"] + b2["h"] / 2
    dist = ((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2) ** 0.5
    return dist < threshold


def generate_preview(image_path: str, regions: list[dict], output_path: str):
    """Generate annotated preview image with bounding boxes."""
    img = cv2.imread(image_path)
    if img is None:
        return

    colors = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255),
        (255, 255, 0), (255, 0, 255), (0, 255, 255),
        (128, 0, 0), (0, 128, 0), (0, 0, 128),
    ]

    for i, region in enumerate(regions):
        b = region["bbox"]
        color = colors[i % len(colors)]
        cv2.rectangle(img, (b["x"], b["y"]), (b["x"] + b["w"], b["y"] + b["h"]), color, 3)
        label = region["id"]
        cv2.putText(img, label, (b["x"], b["y"] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    cv2.imwrite(output_path, img)
    print(f"  Preview saved: {output_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Detect element regions in scene images")
    parser.add_argument("image", help="Path to scene image")
    parser.add_argument("--output-dir", "-o", help="Output directory for preview + JSON")
    parser.add_argument("--min-area", type=float, default=0.01, help="Minimum region area ratio (default: 0.01)")
    parser.add_argument("--full-bbox", action="store_true", help="Only detect full content bbox")
    args = parser.parse_args()

    output_dir = args.output_dir or os.path.dirname(args.image)
    os.makedirs(output_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(args.image))[0]

    if args.full_bbox:
        bbox = detect_full_content_bbox(args.image)
        print(f"\n  Full content bbox: ({bbox['x']}, {bbox['y']}) {bbox['w']}x{bbox['h']}")
        json_path = os.path.join(output_dir, f"{base}_full_bbox.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(bbox, f, ensure_ascii=False, indent=2)
        print(f"  Saved: {json_path}")
    else:
        regions = detect_regions(args.image, min_area_ratio=args.min_area)

        # Save JSON
        json_path = os.path.join(output_dir, f"{base}_regions.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(regions, f, ensure_ascii=False, indent=2)
        print(f"  Regions JSON: {json_path}")

        # Generate preview
        preview_path = os.path.join(output_dir, f"regions_preview.png")
        generate_preview(args.image, regions, preview_path)

        print(f"\n  Detected {len(regions)} regions")
        for r in regions:
            b = r["bbox"]
            print(f"    {r['id']}: ({b['x']}, {b['y']}) {b['w']}x{b['h']}")
