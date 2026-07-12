#!/usr/bin/env python3
"""
extract_contour_paths.py - 从 PNG 提取轮廓路径（Canny + 轮廓追踪），用于笔尖跟踪。

职责：
  1. Canny 边缘检测 → 轮廓追踪
  2. 过滤碎片，RDP 简化
  3. 转 SVG path polyline
  4. 按 element bbox 归属
  5. 按骨架路径分组排序（每条轮廓绑定到最近的骨架路径）

与 extract_drawing_paths.py 的协作：
  - skeleton 路径（extract_drawing_paths）：用于蒙版揭示（100px 宽笔刷，精度要求低）
  - contour 路径（本模块）：用于笔尖跟踪（需要精确对齐可见边缘）

输出：layer: "outline" 标记的路径列表

用法:
    python scripts/extract_contour_paths.py --image images/scene1.png --storyboard output/storyboard.json
"""

import json
import os
import sys
from pathlib import Path


def extract_contour_paths(
    image_path: str,
    elements: list[dict],
    skeleton_paths: list[dict] | None = None,
    canny_threshold1: int = 50,
    canny_threshold2: int = 150,
    min_contour_length: int = 10,
    rdp_epsilon: float = 5.0,
) -> list[dict]:
    """从 PNG 提取轮廓路径（Canny + contour tracing），按骨架路径分组排序。

    Args:
        image_path: PNG 图片路径
        elements: 元素列表（含 bbox）
        skeleton_paths: 已提取的骨架路径（用于分组排序），可选
        canny_threshold1: Canny 低阈值
        canny_threshold2: Canny 高阈值
        min_contour_length: 最小轮廓长度（点数量）
        rdp_epsilon: RDP 简化参数

    Returns:
        [{"d": "M... L...", "elementId": "person", "layer": "outline"}, ...]
    """
    import cv2
    import numpy as np

    # 1. 读取图片 → 灰度
    img = cv2.imread(image_path)
    if img is None:
        print(f"  [ERR] 无法读取图片: {image_path}")
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. Canny 边缘检测
    edges = cv2.Canny(gray, canny_threshold1, canny_threshold2)
    print(f"  Canny 边缘: {np.count_nonzero(edges)} 像素")

    # 3. 轮廓追踪
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    print(f"  原始轮廓: {len(contours)} 条")

    # 4. 过滤 + 简化
    raw_paths = []
    for contour in contours:
        # 展平坐标
        points = [(int(p[0][0]), int(p[0][1])) for p in contour]

        if len(points) < min_contour_length:
            continue

        # RDP 简化
        simplified = _simplify_contour(points, rdp_epsilon)
        if len(simplified) < 2:
            continue

        # 转为 SVG polyline
        d = _contour_to_svg_polyline(simplified)

        # 计算 bbox
        xs = [p[0] for p in simplified]
        ys = [p[1] for p in simplified]
        bbox = {
            "x": int(min(xs)),
            "y": int(min(ys)),
            "w": int(max(xs) - min(xs)),
            "h": int(max(ys) - min(ys)),
        }

        raw_paths.append({
            "d": d,
            "bbox": bbox,
            "length": len(xs),
            "points": simplified,
        })

    print(f"  过滤后: {len(raw_paths)} 条轮廓")

    # 5. 按 element bbox 归属（复用 extract_drawing_paths 的逻辑思路）
    result = _assign_contours_to_elements(raw_paths, elements)

    # 6. 按骨架路径分组排序
    if skeleton_paths:
        result = _sort_by_skeleton_groups(result, skeleton_paths)

    # 7. 标记 layer
    for r in result:
        r["layer"] = "outline"

    return result


def _simplify_contour(
    points: list[tuple[int, int]],
    epsilon: float = 5.0,
) -> list[tuple[int, int]]:
    """Ramer-Douglas-Peucker 轮廓简化。

    复用 extract_drawing_paths._simplify_path 的算法逻辑。
    """
    if len(points) <= 2:
        return points

    def _point_line_distance(p, a, b):
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        nx = ax + t * dx
        ny = ay + t * dy
        return ((px - nx) ** 2 + (py - ny) ** 2) ** 0.5

    stack = [(0, len(points) - 1)]
    keep = {0, len(points) - 1}

    while stack:
        start, end = stack.pop()
        if end - start <= 1:
            continue
        max_dist = 0
        max_idx = start
        for i in range(start + 1, end):
            dist = _point_line_distance(points[i], points[start], points[end])
            if dist > max_dist:
                max_dist = dist
                max_idx = i
        if max_dist > epsilon:
            keep.add(max_idx)
            stack.append((start, max_idx))
            stack.append((max_idx, end))

    return [points[i] for i in sorted(keep)]


def _contour_to_svg_polyline(points: list[tuple[int, int]]) -> str:
    """坐标点列表 → SVG path d 属性。"""
    if not points:
        return ""
    parts = [f"M{points[0][0]} {points[0][1]}"]
    for p in points[1:]:
        parts.append(f"L{p[0]} {p[1]}")
    return " ".join(parts)


def _assign_contours_to_elements(
    raw_paths: list[dict],
    elements: list[dict],
) -> list[dict]:
    """将轮廓路径按 bbox 归属到元素。

    每条路径的 center point 落在哪个 element 的 (padding) bbox 内就归谁。
    未匹配的归入最近的元素。
    """
    if not elements:
        return [{"d": rp["d"], "elementId": "content"} for rp in raw_paths]

    # 扩增 element bbox（15% padding）
    padded = []
    for elem in elements:
        eb = elem.get("bbox", {"x": 0, "y": 0, "w": 1920, "h": 1080})
        pad_x = eb["w"] * 0.15
        pad_y = eb["h"] * 0.15
        padded.append({
            "id": elem["id"],
            "x1": eb["x"] - pad_x,
            "y1": eb["y"] - pad_y,
            "x2": eb["x"] + eb["w"] + pad_x,
            "y2": eb["y"] + eb["h"] + pad_y,
            "cx": eb["x"] + eb["w"] / 2,
            "cy": eb["y"] + eb["h"] / 2,
        })

    result = []
    for rp in raw_paths:
        rb = rp["bbox"]
        cx = rb["x"] + rb["w"] / 2
        cy = rb["y"] + rb["h"] / 2

        matched = None
        for pe in padded:
            if pe["x1"] <= cx <= pe["x2"] and pe["y1"] <= cy <= pe["y2"]:
                matched = pe["id"]
                break

        if not matched:
            # 未匹配 → 最近元素
            nearest = min(
                padded,
                key=lambda pe: ((pe["cx"] - cx) ** 2 + (pe["cy"] - cy) ** 2),
            )
            matched = nearest["id"]

        result.append({
            "d": rp["d"],
            "elementId": matched,
        })

    return result


def _sort_by_skeleton_groups(
    contour_paths: list[dict],
    skeleton_paths: list[dict],
) -> list[dict]:
    """按骨架路径分组排序轮廓路径。

    策略：
      1. 每条轮廓 → 找空间最近的骨架路径 → 绑定到同一组
      2. 组内：按距骨架路径起点的距离排序
      3. 组间：复用骨架路径的原始顺序

    Args:
        contour_paths: 未排序的轮廓路径
        skeleton_paths: 已排序的骨架路径（含 elementId, d）

    Returns:
        排序后的轮廓路径
    """
    if not skeleton_paths:
        return contour_paths

    # 计算每条骨架路径的中心点
    skeleton_centers = []
    for sp in skeleton_paths:
        center = _get_path_center(sp["d"])
        skeleton_centers.append({
            "idx": len(skeleton_centers),
            "elementId": sp.get("elementId", ""),
            "cx": center[0],
            "cy": center[1],
        })

    if not skeleton_centers:
        return contour_paths

    # 为每条轮廓找最近的骨架路径
    contour_groups: dict[int, list[dict]] = {s["idx"]: [] for s in skeleton_centers}
    ungrouped: list[dict] = []

    for cp in contour_paths:
        center = _get_path_center(cp["d"])
        if center is None:
            ungrouped.append(cp)
            continue

        nearest = min(
            skeleton_centers,
            key=lambda sc: (sc["cx"] - center[0]) ** 2 + (sc["cy"] - center[1]) ** 2,
        )
        contour_groups[nearest["idx"]].append(cp)

    # 组内按距骨架路径起点的距离排序
    sorted_paths = []
    for sc in skeleton_centers:
        group = contour_groups[sc["idx"]]
        if not group:
            continue

        # 获取骨架路径起点
        skeleton_path = skeleton_paths[sc["idx"]]
        start_point = _get_path_start(skeleton_path["d"])

        if start_point:
            group.sort(
                key=lambda cp: _min_distance_to_point(cp["d"], start_point)
            )

        sorted_paths.extend(group)

    # 未分组的排在最后
    sorted_paths.extend(ungrouped)

    return sorted_paths


def _get_path_center(d: str) -> tuple[float, float] | None:
    """估算 SVG path 的几何中心。"""
    coords = _extract_coords(d)
    if not coords:
        return None
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _get_path_start(d: str) -> tuple[float, float] | None:
    """获取 SVG path 的第一个坐标点。"""
    coords = _extract_coords(d)
    return coords[0] if coords else None


def _min_distance_to_point(d: str, target: tuple[float, float]) -> float:
    """计算路径上所有点到 target 的最小距离。"""
    coords = _extract_coords(d)
    if not coords:
        return float("inf")
    tx, ty = target
    return min((p[0] - tx) ** 2 + (p[1] - ty) ** 2 for p in coords)


def _extract_coords(d: str) -> list[tuple[float, float]]:
    """从 SVG path d 属性提取坐标点列表。"""
    if not d:
        return []
    coords = []
    # 解析 M x y L x y L x y ...
    parts = d.split()
    i = 0
    while i < len(parts):
        if parts[i] in ("M", "L"):
            if i + 2 < len(parts):
                try:
                    x = float(parts[i + 1])
                    y = float(parts[i + 2])
                    coords.append((x, y))
                except ValueError:
                    pass
                i += 3
            else:
                i += 1
        else:
            i += 1
    return coords


# ── Main (CLI) ──

def main():
    import argparse
    parser = argparse.ArgumentParser(description="PNG → 轮廓路径提取")
    parser.add_argument("--image", "-i", required=True, help="PNG 图片路径")
    parser.add_argument("--storyboard", "-s", required=True, help="storyboard JSON 路径")
    parser.add_argument("--output", "-o", help="输出 JSON 路径")
    parser.add_argument("--skeleton-paths", help="骨架路径 JSON（用于分组排序）")
    args = parser.parse_args()

    with open(args.storyboard, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    # 第一个场景
    scene = storyboard.get("scenes", [{}])[0]
    elements = scene.get("elements", [])

    # 加载骨架路径（可选）
    skeleton_paths = None
    if args.skeleton_paths:
        with open(args.skeleton_paths, "r", encoding="utf-8") as f:
            skeleton_data = json.load(f)
        skeleton_paths = skeleton_data.get("paths", [])

    paths = extract_contour_paths(args.image, elements, skeleton_paths)

    output = {"paths": paths}
    output_path = args.output or "contour-paths.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  输出: {output_path} ({len(paths)} 轮廓路径)")


if __name__ == "__main__":
    main()
