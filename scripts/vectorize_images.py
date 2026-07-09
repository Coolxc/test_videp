#!/usr/bin/env python3
"""
vectorize_images.py - PNG → SVG 矢量化 + 路径分组排序 + 质量门禁。

将每个场景的 PNG 图片转为可动画的 SVG 路径数据，
输出给 Remotion SVGDrawAnimation 组件做 stroke-dashoffset 动画。

输入: images/{scene_id}.png + storyboard.json (elements/bbox)
输出: svg_data/{scene_id}.json (paths + metadata)
      svg_data/svg-data.json (合并文件，供 Remotion 加载)

依赖:
  - vtracer>=0.6.10    (PNG → SVG 矢量化)
  - svgpathtools>=1.6.0 (路径长度 / bbox 计算)
  - opencv-python       (图片预处理)
"""

import json
import os
import sys
import warnings
from pathlib import Path

import cv2
import numpy as np

from config import PROJECT_ROOT, VTRACER_PARAMS, get_image_filename


# ── SVG Path 工具函数 ──

def compute_path_length(d: str) -> float:
    """计算 SVG path 'd' 属性的精确长度（数值积分）。"""
    try:
        from svgpathtools import parse_path
        path = parse_path(d)
        return float(path.length())
    except Exception:
        return 0.0


def compute_path_bbox(d: str) -> dict:
    """计算 SVG path 的精确 bounding box。"""
    try:
        from svgpathtools import parse_path
        path = parse_path(d)
        xmin, xmax, ymin, ymax = path.bbox()
        return {"x": float(xmin), "y": float(ymin), "w": float(xmax - xmin), "h": float(ymax - ymin)}
    except Exception:
        return {"x": 0, "y": 0, "w": 0, "h": 0}


# ── 路径分类 ──

def classify_path(d: str, bbox: dict) -> str:
    """
    判断路径类型：
    - 细长路径（宽高比 > 3 或面积 < 阈值）→ "stroke"：保留为描边，用 dashoffset 动画
    - 宽大路径 → "fill"：保留为填充，用渐显动画
    """
    area = bbox["w"] * bbox["h"]
    aspect = max(bbox["w"], bbox["h"]) / max(1, min(bbox["w"], bbox["h"]))

    if aspect > 3.0 or area < 500:
        return "stroke"
    return "fill"


# ── Bbox 操作 ──

def expand_bbox(bbox: dict, padding_ratio: float = 0.15) -> dict:
    """扩大 bbox，让更多路径被自然归属。"""
    pad_x = bbox["w"] * padding_ratio
    pad_y = bbox["h"] * padding_ratio
    return {
        "x": bbox["x"] - pad_x,
        "y": bbox["y"] - pad_y,
        "w": bbox["w"] + 2 * pad_x,
        "h": bbox["h"] + 2 * pad_y,
    }


def point_in_bbox(px: float, py: float, bbox: dict) -> bool:
    """判断点是否在 bbox 内。"""
    return (bbox["x"] <= px <= bbox["x"] + bbox["w"] and
            bbox["y"] <= py <= bbox["y"] + bbox["h"])


# ── 路径分组 ──

def assign_paths_to_elements(svg_paths: list[dict], elements: list[dict]) -> dict:
    """
    将 SVG 路径按 bbox 归属到对应元素。

    归属规则：路径 bbox 中心点落在哪个 element 的 bbox 内，就归属于该 element。
    不在任何 bbox 内的路径归入 unassignedPaths。
    """
    # 先扩大所有 element 的 bbox
    expanded_elements = []
    for elem in elements:
        e_bbox = elem.get("bbox", {"x": 0, "y": 0, "w": 1920, "h": 1080})
        expanded_elements.append({
            "id": elem["id"],
            "bbox": expand_bbox(e_bbox, 0.15),
        })

    assigned = {elem["id"]: [] for elem in elements}
    unassigned = []

    for path in svg_paths:
        bbox = path.get("bbox", {})
        cx = bbox.get("x", 0) + bbox.get("w", 0) / 2
        cy = bbox.get("y", 0) + bbox.get("h", 0) / 2

        found = False
        for ee in expanded_elements:
            if point_in_bbox(cx, cy, ee["bbox"]):
                assigned[ee["id"]].append(path)
                found = True
                break

        if not found:
            unassigned.append(path)

    return {
        "assigned": assigned,
        "unassigned": unassigned,
    }


def assign_orphan_paths(orphan_paths: list[dict], elements: list[dict]) -> None:
    """将孤立路径归入距离最近的元素。"""
    for path in orphan_paths:
        bbox = path.get("bbox", {})
        cx = bbox.get("x", 0) + bbox.get("w", 0) / 2
        cy = bbox.get("y", 0) + bbox.get("h", 0) / 2

        min_dist = float("inf")
        nearest_elem = None
        for elem in elements:
            eb = elem.get("bbox", {"x": 0, "y": 0, "w": 1920, "h": 1080})
            ecx = eb["x"] + eb["w"] / 2
            ecy = eb["y"] + eb["h"] / 2
            dist = ((cx - ecx) ** 2 + (cy - ecy) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                nearest_elem = elem

        if nearest_elem is not None:
            nearest_elem.setdefault("_orphan_paths", []).append(path)


def order_paths_within_element(paths: list[dict]) -> list[dict]:
    """
    元素内路径排序——模拟人类绘画顺序。

    策略：
    1. 长路径优先（主要轮廓先画，细节后画）
    2. 对相邻路径做 nearest-neighbor 优化（避免笔跳跃太远）
    """
    if len(paths) <= 1:
        return paths

    # 按路径长度降序排列（长路径优先）
    sorted_paths = sorted(paths, key=lambda p: p.get("length", 0), reverse=True)

    # nearest-neighbor 优化：从最长的开始，每次选最近的下一个
    ordered = [sorted_paths[0]]
    remaining = sorted_paths[1:]

    while remaining:
        last = ordered[-1]
        last_bbox = last.get("bbox", {})
        lx = last_bbox.get("x", 0) + last_bbox.get("w", 0) / 2
        ly = last_bbox.get("y", 0) + last_bbox.get("h", 0) / 2

        best_idx = 0
        best_dist = float("inf")
        for i, p in enumerate(remaining):
            pb = p.get("bbox", {})
            px = pb.get("x", 0) + pb.get("w", 0) / 2
            py = pb.get("y", 0) + pb.get("h", 0) / 2
            dist = ((px - lx) ** 2 + (py - ly) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_idx = i

        ordered.append(remaining.pop(best_idx))

    return ordered


# ── 质量门禁 ──

def check_vectorization_readiness(image_path: str) -> list[str]:
    """检查图片是否适合矢量化。返回警告列表。"""
    img = cv2.imread(image_path)
    if img is None:
        return ["无法读取图片，跳过矢量化前检查"]

    warnings_list = []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]

    # 1. 背景是否足够白
    corner_brightness = [
        float(gray[0:20, 0:20].mean()),
        float(gray[0:20, -20:].mean()),
        float(gray[-20:, 0:20].mean()),
        float(gray[-20:, -20:].mean()),
    ]
    avg_corner = sum(corner_brightness) / 4
    if avg_corner < 240:
        warnings_list.append(
            f"背景偏暗 (四角平均亮度={avg_corner:.0f})，可能影响矢量化质量"
        )

    # 2. 内容占比
    content_mask = gray < 200
    content_ratio = content_mask.sum() / gray.size
    if content_ratio < 0.01:
        warnings_list.append("图片内容过少 (非白色像素 < 1%)")
    elif content_ratio > 0.60:
        warnings_list.append(
            "图片内容过密 (非白色像素 > 60%)，矢量化可能产生大量碎片"
        )

    # 3. 灰色过渡区域（抗锯齿/渐变）
    mid_gray = ((gray > 50) & (gray < 200)).sum()
    mid_gray_ratio = mid_gray / gray.size
    if mid_gray_ratio > 0.15:
        warnings_list.append(
            f"灰色过渡区域过多 ({mid_gray_ratio:.1%})，建议增加对比度或使用更清晰的线条"
        )

    return warnings_list


def check_vectorization_output(paths: list[dict], image_area: int) -> list[str]:
    """检查矢量化输出质量。"""
    warnings_list = []

    if len(paths) > 500:
        warnings_list.append(
            f"路径数量过多 ({len(paths)})，建议提高 filter_speckle 或简化原图"
        )

    if len(paths) < 3:
        warnings_list.append(f"路径数量过少 ({len(paths)})，图片可能无足够内容")

    # 检查碎片比例
    small_paths = [
        p for p in paths
        if p["bbox"]["w"] * p["bbox"]["h"] < image_area * 0.001
    ]
    if len(small_paths) > len(paths) * 0.5:
        warnings_list.append(
            f"碎片路径过多 ({len(small_paths)}/{len(paths)})，建议检查原图线条清晰度"
        )

    return warnings_list


# ── 图片尺寸归一化 ──

def normalize_image_size(image_path: str, target_w: int = 1920, target_h: int = 1080) -> bool:
    """等比缩放图片到目标尺寸，白色 padding 填充。返回 True 如果已修改。"""
    img = cv2.imread(image_path)
    if img is None:
        return False

    h, w = img.shape[:2]
    if w == target_w and h == target_h:
        return False  # 已经是目标尺寸

    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

    canvas = np.full((target_h, target_w, 3), 255, dtype=np.uint8)
    y_off = (target_h - new_h) // 2
    x_off = (target_w - new_w) // 2
    canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
    cv2.imwrite(image_path, canvas)
    return True


# ── 矢量化参数合并 ──

def get_vtracer_params(scene: dict, meta: dict) -> dict:
    """合并 meta 级和 scene 级矢量化参数，scene 级覆盖 meta 级。"""
    base = dict(VTRACER_PARAMS)
    meta_override = meta.get("vectorize", {})
    scene_override = scene.get("vectorize", {})
    base.update(meta_override)
    base.update(scene_override)
    return base


# ── 矢量化执行器（使用 potrace CLI，避免 vtracer Python/Rust FFI segfault）──

def _run_potrace(image_path: str, params: dict) -> bytes:
    """
    使用 potrace CLI 将图片转为 SVG。

    流程: PNG → OpenCV 二值化 → PBM → potrace → SVG

    potrace 参数映射:
      - filter_speckle → -t (turdsize, 去噪点)
      - corner_threshold → -a (angle, 拐角检测)
    """
    import subprocess
    import struct
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pbm", delete=False) as f:
        pbm_path = f.name
    svg_tmp = tempfile.mktemp(suffix=".svg")

    try:
        # Step 1: 二值化
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise RuntimeError(f"无法读取图片: {image_path}")

        _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        binary = 255 - binary  # 反转: 线条=白(前景), 背景=黑

        # Step 2: 写 PBM (P4 格式)
        h, w = binary.shape
        with open(pbm_path, "wb") as f:
            f.write(f"P4\n{w} {h}\n".encode())
            # Pack bits row by row
            for row in binary:
                packed = bytearray()
                for i in range(0, w, 8):
                    byte = 0
                    for j in range(8):
                        if i + j < w and row[i + j] > 127:
                            byte |= (1 << (7 - j))
                    packed.append(byte)
                f.write(packed)

        # Step 3: potrace
        speckle = params.get("filter_speckle", 8)
        angle = params.get("corner_threshold", 45)

        cmd = [
            "potrace", "-s", "--progress",
            "-W", "1920", "-H", "1080",
            "-t", str(speckle),
            "-a", str(angle),
            "-o", svg_tmp, pbm_path,
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=120)

        if result.returncode != 0:
            raise RuntimeError(
                f"potrace 失败 (exit={result.returncode}):\n"
                f"  {result.stderr.decode(errors='replace')[:500]}"
            )

        with open(svg_tmp, "rb") as f:
            svg_bytes = f.read()

        print(f"  potrace OK: {len(svg_bytes)} bytes SVG")
        return svg_bytes

    except FileNotFoundError:
        raise RuntimeError("potrace 未安装。请运行: sudo apt install potrace")
    finally:
        for p in (pbm_path, svg_tmp):
            if os.path.exists(p):
                os.unlink(p)


# ── 主矢量化函数 ──

def vectorize_scene(
    image_path: str,
    elements: list[dict],
    scene_id: str,
    vtracer_params: dict | None = None,
    image_size: tuple[int, int] = (1920, 1080),
) -> dict:
    """
    将一张场景图片矢量化并按元素分组。

    Args:
        image_path: PNG 图片路径
        elements: 此场景的元素列表（含 bbox）
        scene_id: 场景 ID
        vtracer_params: vtracer 参数覆盖
        image_size: 图片目标尺寸 (w, h)

    Returns:
        {
            "sceneId": "...",
            "viewBox": "0 0 W H",
            "elements": [
                {
                    "id": "...",
                    "paths": [
                        {
                            "d": "M100,200 C...",
                            "stroke": "#000000",
                            "strokeWidth": 2.5,
                            "fill": "none",
                            "length": 342.5,
                            "bbox": {"x":..., "y":..., "w":..., "h":...},
                            "type": "stroke"
                        },
                    ],
                    "totalLength": 1234.5,
                    "narration": "...",
                }
            ],
            "unassignedPaths": [...]
        }
    """
    params = vtracer_params or VTRACER_PARAMS

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片不存在: {image_path}")

    # 矢量化前检查
    pre_warnings = check_vectorization_readiness(image_path)
    for w in pre_warnings:
        print(f"  [WARN] 矢量化前检查: {w}")

    # 执行矢量化（使用 potrace CLI，避免 vtracer FFI segfault）
    svg_bytes = _run_potrace(image_path, params)

    # 解析 SVG XML
    import xml.etree.ElementTree as ET
    root = ET.fromstring(svg_bytes)

    # 收集所有 path 元素
    ns = {"svg": "http://www.w3.org/2000/svg"}
    raw_paths = []
    for path_elem in root.findall(".//svg:path", ns):
        d = path_elem.get("d", "")
        if not d:
            continue
        raw_paths.append(d)

    # 构建路径数据
    img_w, img_h = image_size
    view_box = f"0 0 {img_w} {img_h}"
    area = img_w * img_h

    parsed_paths = []
    for d in raw_paths:
        bbox = compute_path_bbox(d)
        length = compute_path_length(d)
        ptype = classify_path(d, bbox)
        parsed_paths.append({
            "d": d,
            "stroke": "#000000",
            "strokeWidth": 2.5,
            "fill": "none",
            "length": length,
            "bbox": bbox,
            "type": ptype,
        })

    # 矢量化后质量检查
    post_warnings = check_vectorization_output(parsed_paths, area)
    for w in post_warnings:
        print(f"  [WARN] 矢量化后检查: {w}")

    # 路径分组
    result = assign_paths_to_elements(parsed_paths, elements)
    assigned = result["assigned"]
    unassigned_paths = result["unassigned"]

    # 构建输出
    out_elements = []
    for elem in elements:
        eid = elem["id"]
        elem_paths = assigned.get(eid, [])
        # 排序
        elem_paths = order_paths_within_element(elem_paths)
        # 计算总长度
        total_length = sum(p.get("length", 0) for p in elem_paths)

        out_elements.append({
            "id": eid,
            "paths": elem_paths,
            "totalLength": total_length,
            "narration": elem.get("narration", ""),
        })

    # 处理 unassigned: 就近归属
    assign_orphan_paths(unassigned_paths, out_elements)
    # 将 _orphan_paths 合并到对应元素
    remaining_unassigned = []
    for elem in out_elements:
        orphans = elem.pop("_orphan_paths", [])
        if orphans:
            elem["paths"].extend(orphans)
            elem["totalLength"] += sum(p.get("length", 0) for p in orphans)

    # 仍有剩余的 unassigned → 创建 _cleanup 元素
    if unassigned_paths:
        # 过滤掉已被分配走的
        still_unassigned = [p for p in unassigned_paths
                            if not any(p in elem.get("paths", []) for elem in out_elements)]
        if still_unassigned:
            still_unassigned = order_paths_within_element(still_unassigned)
            total_len = sum(p.get("length", 0) for p in still_unassigned)
            out_elements.append({
                "id": "_cleanup",
                "paths": still_unassigned,
                "totalLength": total_len,
                "narration": "",
            })

    # 去掉 bbox 字段（只在内部使用，不输出）
    for elem in out_elements:
        for p in elem.get("paths", []):
            p.pop("bbox", None)

    return {
        "sceneId": scene_id,
        "viewBox": view_box,
        "elements": out_elements,
    }


def vectorize_all_scenes(
    storyboard_path: str,
    images_dir: str,
    output_dir: str,
) -> dict:
    """批量矢量化所有场景。"""
    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    meta = storyboard.get("meta", {})
    scenes = storyboard.get("scenes", [])
    img_w = meta.get("width", 1920)
    img_h = meta.get("height", 1080)

    # 输出目录
    svg_data_dir = Path(output_dir) / "svg_data"
    svg_data_dir.mkdir(parents=True, exist_ok=True)

    all_svg_data = {}

    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        image_path = os.path.join(images_dir, get_image_filename(scene_id))
        elements = scene.get("elements", [])

        print(f"\n  矢量化: {scene_id} ({image_path})")

        if not os.path.exists(image_path):
            print(f"  [WARN] 图片不存在，跳过: {image_path}")
            continue

        # 预处理：尺寸归一化
        normalize_image_size(image_path, img_w, img_h)

        # 矢量化参数
        params = get_vtracer_params(scene, meta)

        # 执行
        svg_data = vectorize_scene(
            image_path, elements, scene_id,
            vtracer_params=params,
            image_size=(img_w, img_h),
        )

        # 写入单个文件
        out_path = svg_data_dir / f"{scene_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(svg_data, f, ensure_ascii=False)
        print(f"  输出: {out_path} ({len(svg_data['elements'])} elements)")

        all_svg_data[scene_id] = {
            "viewBox": svg_data["viewBox"],
            "elements": [
                {
                    "id": elem["id"],
                    "paths": elem["paths"],
                    "totalLength": elem["totalLength"],
                }
                for elem in svg_data["elements"]
            ],
        }

    # 写入合并文件
    merged_path = svg_data_dir / "svg-data.json"
    with open(merged_path, "w", encoding="utf-8") as f:
        json.dump(all_svg_data, f, ensure_ascii=False)
    print(f"\n  合并 SVG 数据: {merged_path} ({len(all_svg_data)} scenes)")

    return all_svg_data


# ── 命令行入口 ──

def main():
    import argparse
    parser = argparse.ArgumentParser(description="PNG → SVG 矢量化管线")
    parser.add_argument("--storyboard", "-s", required=True, help="storyboard.json 路径")
    parser.add_argument("--images-dir", "-i", help="图片目录")
    parser.add_argument("--output-dir", "-o", help="输出目录")
    args = parser.parse_args()

    with open(args.storyboard, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    topic = storyboard.get("meta", {}).get("topic", "untitled")
    output_dir = args.output_dir or str(PROJECT_ROOT / "output" / topic)
    images_dir = args.images_dir or os.path.join(output_dir, "images")

    vectorize_all_scenes(args.storyboard, images_dir, output_dir)


if __name__ == "__main__":
    main()
