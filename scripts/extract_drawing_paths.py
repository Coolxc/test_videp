#!/usr/bin/env python3
"""
extract_drawing_paths.py - 从 PNG 图片中提取绘制中心线路径。

输入: images/{scene_id}.png + storyboard.json (elements/bbox)
输出: drawing_paths/{scene_id}.json (paths + element assignment)
      drawing_paths/drawing-paths.json (合并文件，供 Remotion 加载)

技术: scikit-image skeletonize → 1px 骨架 → 连通分量(8-connectivity)
      → nearest-neighbor 排序 → SVG polyline → 按 element bbox 分组

路径用途: 作为 Remotion MaskRevealAnimation 的蒙版引导路径。
蒙版笔刷宽度 80-100px，对路径精度要求低（容错 20px+）。

与旧 vectorize_images.py 的根本区别:
  - 输出的是开放中心线路径（非 potrace 闭合轮廓）
  - 路径坐标在 PNG 像素空间（0-1920 / 0-1080）
  - 不需要 length / viewBox / strokeWidth 等信息
"""

import json
import os
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import label
from skimage.morphology import skeletonize

from config import PROJECT_ROOT, get_image_filename


def extract_drawing_paths(image_path: str, elements: list[dict]) -> list[dict]:
    """
    从 PNG 提取中心线路径，按 element bbox 分组。

    Args:
        image_path: PNG 图片路径
        elements: 此场景的元素列表（含 bbox）

    Returns:
        [{"d": "M120 350 L180 320 ...", "elementId": "person"}, ...]
    """
    img_pil = Image.open(image_path).convert("L")
    img = np.array(img_pil)

    # 二值化：黑色内容 = True（前景）
    binary = img < 200

    # 形态学骨架化 → 1px 宽中心线
    skeleton = skeletonize(binary)

    # 8-connectivity 连通分量标记（对骨架线连接友好）
    struct8 = np.ones((3, 3), dtype=bool)
    labeled, n = label(skeleton, structure=struct8)

    # 提取每条路径的坐标点
    raw_paths = []
    for i in range(1, n + 1):
        ys, xs = np.where(labeled == i)
        if len(xs) < 5:
            continue  # 过滤过短路径（噪点）

        points = list(zip(xs.tolist(), ys.tolist()))
        ordered = _order_points_nearest_neighbor(points)
        d = _points_to_svg_polyline(ordered)

        bbox = {
            "x": int(xs.min()),
            "y": int(ys.min()),
            "w": int(xs.max() - xs.min()),
            "h": int(ys.max() - ys.min()),
        }
        raw_paths.append({"d": d, "bbox": bbox, "length": len(xs)})

    print(f"  骨架: {n} 连通分量 → {len(raw_paths)} 有效路径")

    # 按元素 bbox 分组
    return _assign_paths_to_elements(raw_paths, elements)


def _simplify_path(points: list[tuple[int, int]], epsilon: float = 2.0) -> list[tuple[int, int]]:
    """
    Ramer-Douglas-Peucker 路径简化。

    骨架化输出的路径包含每个像素点，但对于 80-100px 宽的蒙版笔刷，
    每 2px 一个控制点就够。简化后 Remotion 的 getPointAtLength 性能更好。
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

    # 迭代 RDP
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


def _points_to_svg_polyline(points: list[tuple[int, int]]) -> str:
    """坐标点列表 → SVG path d 属性（polyline），含 RDP 简化。"""
    if not points:
        return ""
    simplified = _simplify_path(points, epsilon=5.0)
    parts = [f"M{simplified[0][0]} {simplified[0][1]}"]
    for p in simplified[1:]:
        parts.append(f"L{p[0]} {p[1]}")
    return " ".join(parts)


def _order_points_nearest_neighbor(
    points: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """
    Nearest-neighbor 排序：将散点连成连续路径。

    因为骨架化输出的点集接近连续，nearest-neighbor 就足够。
    对长路径（>500 点）采用采样加速——取 1/4 锚点排序后插回。
    """
    n = len(points)
    if n <= 2:
        return points

    # 长路径优化：分治排序
    if n > 500:
        # 取 1/4 锚点做全局排序
        step = max(1, n // 250)
        anchor_indices = list(range(0, n, step))
        anchor_points = [points[i] for i in anchor_indices]
        anchor_ordered = _nearest_neighbor_sort(anchor_points)

        # 用锚点顺序重建全序列
        result = []
        used = set(anchor_indices)
        # 为每对相邻锚点插入中间的原始点
        for ai, anchor_idx in enumerate(anchor_ordered):
            orig_idx = anchor_indices[anchor_points.index(anchor_idx)]
            # 插入此锚点之前的点（按原始顺序）
            start = (anchor_indices[anchor_indices.index(orig_idx) - 1] + 1) if ai > 0 else 0
            end = orig_idx
            for j in range(start, end):
                if j not in used:
                    result.append(points[j])
                    used.add(j)
            result.append(points[orig_idx])
            used.add(orig_idx)
        # 追加剩余点
        for j in range(n):
            if j not in used:
                result.append(points[j])
        return result

    return _nearest_neighbor_sort(points)


def _nearest_neighbor_sort(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """纯 nearest-neighbor 排序。"""
    if len(points) <= 2:
        return points

    pts = list(points)
    ordered = [pts[0]]
    remaining_indices = set(range(1, len(pts)))

    while remaining_indices:
        last_x, last_y = ordered[-1]
        best_idx = min(
            remaining_indices,
            key=lambda i: (pts[i][0] - last_x) ** 2 + (pts[i][1] - last_y) ** 2,
        )
        ordered.append(pts[best_idx])
        remaining_indices.remove(best_idx)

    return ordered


def _assign_paths_to_elements(
    raw_paths: list[dict],
    elements: list[dict],
) -> list[dict]:
    """
    将路径按 bbox 归属到元素。

    归属规则：路径 bbox 中心点落在哪个 element 的 (padding) bbox 内，
    就归属于该 element。未匹配的路径归入最近的元素。
    """
    if not elements:
        # 没有元素定义时，所有路径标记为 "content"
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
    assigned = set()

    for i, rp in enumerate(raw_paths):
        rb = rp["bbox"]
        cx = rb["x"] + rb["w"] / 2
        cy = rb["y"] + rb["h"] / 2

        matched = None
        for pe in padded:
            if pe["x1"] <= cx <= pe["x2"] and pe["y1"] <= cy <= pe["y2"]:
                matched = pe["id"]
                assigned.add(i)
                break

        if matched:
            result.append({"d": rp["d"], "elementId": matched})

    # 未分配路径 → 最近元素
    for i, rp in enumerate(raw_paths):
        if i in assigned:
            continue
        rb = rp["bbox"]
        cx = rb["x"] + rb["w"] / 2
        cy = rb["y"] + rb["h"] / 2

        nearest = min(
            padded,
            key=lambda pe: ((pe["cx"] - cx) ** 2 + (pe["cy"] - cy) ** 2),
        )
        result.append({"d": rp["d"], "elementId": nearest["id"]})

    return result


def extract_all_scenes(storyboard_path: str, images_dir: str, output_dir: str) -> dict:
    """批量提取所有场景的中心线路径。"""
    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    scenes = storyboard.get("scenes", [])

    drawing_paths_dir = Path(output_dir) / "drawing_paths"
    drawing_paths_dir.mkdir(parents=True, exist_ok=True)

    all_paths: dict[str, dict] = {}

    for scene in scenes:
        scene_id = scene.get("id", "unknown")
        image_path = os.path.join(images_dir, get_image_filename(scene_id))
        elements = scene.get("elements", [])

        print(f"\n  处理: {scene_id} ({image_path})")

        if not os.path.exists(image_path):
            print(f"  [WARN] 图片不存在，跳过: {image_path}")
            continue

        paths = extract_drawing_paths(image_path, elements)

        scene_data = {"paths": paths}
        all_paths[scene_id] = scene_data

        # 写入单文件
        out_path = drawing_paths_dir / f"{scene_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(scene_data, f, ensure_ascii=False)
        print(f"  输出: {out_path} ({len(paths)} paths)")

    # 写入合并文件
    merged_path = drawing_paths_dir / "drawing-paths.json"
    with open(merged_path, "w", encoding="utf-8") as f:
        json.dump(all_paths, f, ensure_ascii=False)
    print(f"\n  合并数据: {merged_path} ({len(all_paths)} scenes)")

    return all_paths


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PNG → 中心线路径提取")
    parser.add_argument("--storyboard", "-s", required=True)
    parser.add_argument("--images-dir", "-i")
    parser.add_argument("--output-dir", "-o")
    args = parser.parse_args()

    with open(args.storyboard, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    topic = storyboard.get("meta", {}).get("topic", "untitled")
    output_dir = args.output_dir or str(PROJECT_ROOT / "output" / topic)
    images_dir = args.images_dir or os.path.join(output_dir, "images")

    extract_all_scenes(args.storyboard, images_dir, output_dir)


if __name__ == "__main__":
    main()
