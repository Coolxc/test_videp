#!/usr/bin/env python3
"""
extract_drawing_paths.py - 从 PNG 图片中提取绘制中心线路径。

输入: images/{scene_id}.png + storyboard.json (elements/bbox)
输出: drawing_paths/{scene_id}.json (paths + element assignment)
      drawing_paths/drawing-paths.json (合并文件，供 Remotion 加载)

技术: scikit-image skeletonize → 1px 骨架 → 交叉点拆分
      → 链式遍历 → SVG polyline → 按 element bbox 分组

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
from scipy.ndimage import label, convolve
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

    # 交叉点拆分 + 链式遍历（替代原来的连通分量+最近邻排序）
    branches = _extract_branches(skeleton, min_branch_length=5)

    # 提取每条路径的坐标点
    raw_paths = []
    for ordered in branches:
        xs = [p[0] for p in ordered]
        ys = [p[1] for p in ordered]

        d = _points_to_svg_polyline(ordered)

        bbox = {
            "x": int(min(xs)),
            "y": int(min(ys)),
            "w": int(max(xs) - min(xs)),
            "h": int(max(ys) - min(ys)),
        }
        raw_paths.append({"d": d, "bbox": bbox, "length": len(xs)})

    print(f"  骨架: {len(branches)} 分支 → {len(raw_paths)} 有效路径")

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


def _extract_branches(skeleton: np.ndarray, min_branch_length: int = 3) -> list[list[tuple[int, int]]]:
    """在交叉点拆分骨架为简单分支链，返回逐条遍历的坐标列表。

    Args:
        skeleton: 二值骨架图 (H x W)，True = 前景像素
        min_branch_length: 分支最小长度，小于此值被过滤

    Returns:
        list of ordered (x, y) coordinate lists, 每条是一个无分支的简单链
    """
    # 1. 计算 8-连通邻居数
    kernel = np.array([[1, 1, 1],
                       [1, 0, 1],
                       [1, 1, 1]], dtype=np.uint8)
    nbr_count = convolve(skeleton.astype(np.uint8), kernel, mode='constant', cval=0)
    nbr_count = nbr_count * skeleton

    # 2. 标记交叉点（邻居数 > 2）
    junctions = (nbr_count > 2) & skeleton

    # 3. 移除交叉点，骨架分裂为独立分支
    branch_mask = skeleton & ~junctions

    # 4. 8-connectivity 连通分量标记
    struct8 = np.ones((3, 3), dtype=bool)
    labeled, n = label(branch_mask, structure=struct8)

    # 5. 遍历每个分量
    branches = []
    for i in range(1, n + 1):
        component = (labeled == i)
        ordered = _walk_chain(component)
        if len(ordered) >= min_branch_length:
            branches.append(ordered)

    return branches


def _walk_chain(mask: np.ndarray) -> list[tuple[int, int]]:
    """从端点遍历一条简单链（无分支），返回有序坐标列表。

    对闭合环路（无端点），从最上方像素开始绕行。

    Args:
        mask: 单条简单链的二值图 (H x W)，True = 前景像素

    Returns:
        ordered (x, y) coordinate list
    """
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return []

    points = set(zip(xs.tolist(), ys.tolist()))

    def count_neighbors(px: int, py: int) -> int:
        """计算 (px, py) 在 points 中的 8-连通邻居数。"""
        count = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                if (px + dx, py + dy) in points:
                    count += 1
        return count

    # 找端点（邻居数 ≤ 1）
    endpoints = [(x, y) for (x, y) in points if count_neighbors(x, y) <= 1]

    if endpoints:
        # 从最上方的端点开始（y 最小，同 y 取 x 最小）
        start = min(endpoints, key=lambda p: (p[1], p[0]))
    else:
        # 闭合环路：从最上方像素开始
        start = min(points, key=lambda p: (p[1], p[0]))

    # 逐步遍历：每步找唯一的未访问 8-邻域点
    ordered = [start]
    visited = {start}
    current = start

    while True:
        cx, cy = current
        found = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                neighbor = (cx + dx, cy + dy)
                if neighbor in points and neighbor not in visited:
                    found = neighbor
                    break
            if found is not None:
                break

        if found is None:
            break

        ordered.append(found)
        visited.add(found)
        current = found

    return ordered


def _sort_element_paths(elem_paths: list, strategy: str, elem_bbox: dict) -> list:
    """根据 drawStrategy 对元素内路径排序。"""
    if strategy == "top_down":
        return sorted(elem_paths, key=lambda x: x[1]["bbox"]["y"])

    elif strategy == "bottom_up":
        return sorted(elem_paths, key=lambda x: x[1]["bbox"]["y"], reverse=True)

    elif strategy == "left_right":
        return sorted(elem_paths, key=lambda x: x[1]["bbox"]["x"])

    elif strategy == "outline_first":
        by_length = sorted(elem_paths, key=lambda x: x[1]["length"], reverse=True)
        split = max(1, len(by_length) // 5)
        outline = _greedy_spatial_walk(by_length[:split], elem_bbox)
        detail = _greedy_spatial_walk(by_length[split:], elem_bbox)
        return outline + detail

    elif strategy == "center_out":
        cx = elem_bbox["x"] + elem_bbox["w"] / 2
        cy = elem_bbox["y"] + elem_bbox["h"] / 2
        return sorted(elem_paths,
                      key=lambda x: _path_center_dist(x[1], cx, cy))

    else:  # spatial_walk (default)
        return _greedy_spatial_walk(elem_paths, elem_bbox)


def _greedy_spatial_walk(paths: list, elem_bbox: dict) -> list:
    """空间邻近遍历：从元素左上角开始，每次画最近的未画路径。"""
    if len(paths) <= 1:
        return paths
    remaining = list(range(len(paths)))
    start_x, start_y = elem_bbox["x"], elem_bbox["y"]
    first = min(remaining,
                key=lambda j: _path_center_dist(paths[j][1], start_x, start_y))
    ordered = [first]
    remaining.remove(first)
    while remaining:
        last = paths[ordered[-1]][1]
        lx = last["bbox"]["x"] + last["bbox"]["w"] / 2
        ly = last["bbox"]["y"] + last["bbox"]["h"] / 2
        nearest = min(remaining,
                      key=lambda j: _path_center_dist(paths[j][1], lx, ly))
        ordered.append(nearest)
        remaining.remove(nearest)
    return [paths[j] for j in ordered]


def _path_center_dist(rp, x, y):
    cx = rp["bbox"]["x"] + rp["bbox"]["w"] / 2
    cy = rp["bbox"]["y"] + rp["bbox"]["h"] / 2
    return (cx - x) ** 2 + (cy - y) ** 2


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

    # 第一步：为每条路径确定归属元素
    path_elem_map: dict[int, str] = {}
    for i, rp in enumerate(raw_paths):
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

        path_elem_map[i] = matched

    # 第二步：按 elements 顺序分组，每组用对应的 drawStrategy 排序
    result = []
    for elem in elements:
        eid = elem["id"]
        elem_paths = [(i, rp) for i, rp in enumerate(raw_paths) if path_elem_map[i] == eid]
        if not elem_paths:
            continue

        strategy = elem.get("drawStrategy", "spatial_walk")
        eb = elem.get("bbox", {"x": 0, "y": 0, "w": 1920, "h": 1080})
        sorted_paths = _sort_element_paths(elem_paths, strategy, eb)

        for i, rp in sorted_paths:
            result.append({"d": rp["d"], "elementId": eid})

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
