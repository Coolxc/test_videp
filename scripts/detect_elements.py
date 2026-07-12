#!/usr/bin/env python3
"""
detect_elements.py - 元素 bbox 检测模块。

主方案：LLM Vision API（deepseek-v4-pro OpenAI 兼容格式）
降级方案：OpenCV 图像处理（无 API 依赖）

流程：
  1. 优先调用 DeepSeek Vision API 检测 bbox
  2. Vision 失败 → OpenCV 内容区域检测
  3. 校验 bbox（不越界、面积≥1%、IoU≤0.3）
  4. --review 模式：输出带标注的预览图

用法:
    python scripts/detect_elements.py --storyboard output/storyboard-skeleton.json --images-dir output/xxx/images
"""

import json
import os
import sys
from pathlib import Path
from itertools import combinations


# ── Bbox Validation ──

def iou(a: dict, b: dict) -> float:
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(a["x"] + a["w"], b["x"] + b["w"])
    y2 = min(a["y"] + a["h"], b["y"] + b["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = a["w"] * a["h"] + b["w"] * b["h"] - intersection
    return intersection / union if union > 0 else 0


def validate_bboxes(
    bboxes: list[dict],
    img_w: int = 1920,
    img_h: int = 1080,
) -> tuple[bool, list[str]]:
    errors = []
    for b in bboxes:
        if b["x"] < 0 or b["y"] < 0:
            errors.append(f"bbox ({b.get('id', '?')}) 左上角越界")
        if b["x"] + b["w"] > img_w:
            errors.append(f"bbox ({b.get('id', '?')}) 右边界越界")
        if b["y"] + b["h"] > img_h:
            errors.append(f"bbox ({b.get('id', '?')}) 下边界越界")
        min_area = img_w * img_h * 0.01
        if b["w"] * b["h"] < min_area:
            errors.append(f"bbox ({b.get('id', '?')}) 面积过小")
    for i, j in combinations(range(len(bboxes)), 2):
        overlap = iou(bboxes[i], bboxes[j])
        if overlap > 0.3:
            errors.append(f"bbox {bboxes[i].get('id', i)} 和 {bboxes[j].get('id', j)} IoU={overlap:.2f}>0.3")
    return len(errors) == 0, errors


# ── Annotation Preview ──

def draw_bbox_preview(image_path: str, elements: list[dict], output_path: str):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  [WARN] PIL not available, skipping preview")
        return
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    colors = [
        (66, 133, 244), (52, 168, 83), (251, 188, 4), (234, 67, 53),
        (142, 68, 173), (230, 126, 34), (46, 204, 113), (231, 76, 60),
    ]
    font = None
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
    except (OSError, IOError):
        try:
            font = ImageFont.load_default()
        except Exception:
            pass
    for i, elem in enumerate(elements):
        bbox = elem.get("bbox", {})
        if "x" not in bbox:
            continue
        color = colors[i % len(colors)]
        draw.rectangle([bbox["x"], bbox["y"], bbox["x"] + bbox["w"], bbox["y"] + bbox["h"]], outline=color, width=3)
        label = f"{i+1}. {elem.get('description', elem.get('id', '?'))[:20]}"
        if font:
            bb = draw.textbbox((0, 0), label, font=font)
            tw, th = bb[2] - bb[0] + 10, bb[3] - bb[1] + 6
            draw.rectangle([bbox["x"], bbox["y"] - th, bbox["x"] + tw, bbox["y"]], fill=color)
            draw.text((bbox["x"] + 5, bbox["y"] - th + 3), label, fill=(255, 255, 255), font=font)
    img.save(output_path)
    print(f"  Bbox 预览图: {output_path}")


# ── OpenCV Fallback ──

def _detect_opencv(
    image_path: str,
    elements: list[dict],
    img_w: int,
    img_h: int,
) -> list[dict]:
    """OpenCV 内容区域检测（Vision API 的降级方案）。"""
    if len(elements) <= 1:
        return [{**elements[0], "bbox": {"x": 0, "y": 0, "w": img_w, "h": img_h}}]

    try:
        import cv2
        import numpy as np
    except ImportError:
        print("  [OpenCV] 不可用，使用垂直等分")
        return _fallback_split(elements, img_w, img_h)

    n = len(elements)
    gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return _fallback_split(elements, img_w, img_h)

    # 反二值化 + 闭运算合并笔触
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    kernel_size = 31 if n <= 2 else 21 if n <= 4 else 11
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    # 连通分量
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    components = []
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < img_w * img_h * 0.005:
            continue
        x, y, cw, ch = (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
                         stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT])
        components.append({"x": max(0, x - 10), "y": max(0, y - 10),
                           "w": min(img_w, cw + 20), "h": min(img_h, ch + 20), "area": area})

    components.sort(key=lambda c: c["area"], reverse=True)

    if len(components) >= n:
        comps = sorted(components[:n], key=lambda c: (c["y"], c["x"]))
    elif len(components) > 0:
        comps = _split_components(components, n, img_w, img_h)
    else:
        return _fallback_split(elements, img_w, img_h)

    result = []
    for i, elem in enumerate(elements):
        if i < len(comps):
            result.append({**elem, "bbox": {"x": comps[i]["x"], "y": comps[i]["y"],
                                           "w": comps[i]["w"], "h": comps[i]["h"]}})
        else:
            result.append({**elem, "bbox": {"x": 0, "y": img_h * i // n, "w": img_w, "h": img_h // n}})
    return result


def _split_components(components: list[dict], target: int, img_w: int, img_h: int) -> list[dict]:
    result = list(components)
    while len(result) < target:
        largest = max(result, key=lambda c: c["area"])
        if largest["w"] > largest["h"] * 1.5:
            mid_x = largest["x"] + largest["w"] // 2
            a, b = {"x": largest["x"], "y": largest["y"], "w": mid_x - largest["x"], "h": largest["h"], "area": (mid_x - largest["x"]) * largest["h"]}, \
                   {"x": mid_x, "y": largest["y"], "w": largest["x"] + largest["w"] - mid_x, "h": largest["h"], "area": (largest["x"] + largest["w"] - mid_x) * largest["h"]}
        else:
            mid_y = largest["y"] + largest["h"] // 2
            a, b = {"x": largest["x"], "y": largest["y"], "w": largest["w"], "h": mid_y - largest["y"], "area": largest["w"] * (mid_y - largest["y"])}, \
                   {"x": largest["x"], "y": mid_y, "w": largest["w"], "h": largest["y"] + largest["h"] - mid_y, "area": largest["w"] * (largest["y"] + largest["h"] - mid_y)}
        result.remove(largest)
        result.extend([a, b])
        if len(result) > target * 3:
            break
    return result[:target]


def _fallback_split(elements: list[dict], img_w: int = 1920, img_h: int = 1080) -> list[dict]:
    n = len(elements)
    h = img_h // n
    return [{**e, "bbox": {"x": 0, "y": i * h, "w": img_w, "h": h if i < n - 1 else img_h - i * h}}
            for i, e in enumerate(elements)]


# ── Vision API Detection ──

def _detect_vision(
    image_path: str,
    elements: list[dict],
    img_w: int,
    img_h: int,
    max_retries: int = 3,
) -> list[dict] | None:
    """通过 DeepSeek Vision API 检测 bbox。失败返回 None。"""
    try:
        from llm_client import call_deepseek_vision_json
    except (ImportError, RuntimeError) as e:
        print(f"  [Vision] LLM 不可用: {e}")
        return None

    elem_descs = "\n".join(f"  - {e['id']}: {e.get('description', '?')}" for e in elements)
    has_draw_order = any(e.get("drawOrder") for e in elements)

    system_prompt = """你是一位专业的白板视频元素定位专家。
分析白板手绘图片，检测每个元素在画面中的精确位置（bbox）。

规则：
- 输出每个元素的 bbox（像素坐标）：{x, y, w, h}
- 图片尺寸 1920×1080
- bbox 不越界、面积≥画布1%、元素间IoU≤0.3

输出 JSON：
{
  "elements": [
    {"id": "element_id", "bbox": {"x": 100, "y": 200, "w": 300, "h": 250}}
  ]
}"""

    if not has_draw_order:
        system_prompt += "\n\n同时根据遮挡关系和语义推断绘制顺序，在输出中按绘制顺序排列 elements。"

    user_prompt = (
        f"检测以下元素在图片中的精确位置（{img_w}×{img_h}像素）：\n"
        f"{elem_descs}\n"
        "返回每个元素的 bbox。"
    )

    for attempt in range(max_retries):
        try:
            print(f"  [Vision] bbox 检测尝试 {attempt + 1}/{max_retries}...")
            result = call_deepseek_vision_json(
                system_prompt, user_prompt, image_path,
                temperature=0.3, max_tokens=4000,
            )
            detected = result.get("elements", [])
            if not detected:
                print(f"  [Vision] 未返回元素")
                continue

            elem_map = {e["id"]: e for e in elements}
            matched = []
            for d in detected:
                eid = d.get("id", "")
                if eid in elem_map:
                    matched.append({**elem_map[eid], "bbox": d.get("bbox", {})})
                elif eid:
                    # Vision 可能用序号命名，尝试按顺序匹配
                    pass

            # 确保所有元素都有 bbox
            matched_ids = {m["id"] for m in matched}
            for elem in elements:
                if elem["id"] not in matched_ids:
                    matched.append({**elem, "bbox": {"x": 0, "y": 0, "w": img_w, "h": img_h}})

            bboxes_to_check = [{**m["bbox"], "id": m["id"]} for m in matched]
            is_valid, errors = validate_bboxes(bboxes_to_check, img_w, img_h)

            if not is_valid:
                print(f"  [WARN] bbox 校验失败: {'; '.join(errors[:3])}")
                continue

            print(f"  [Vision OK] 检测到 {len(matched)} 个元素 bbox")
            return matched

        except Exception as e:
            print(f"  [WARN] 第 {attempt+1} 次尝试失败: {e}")

    return None


# ── Main Entry ──

def detect_element_bboxes(
    image_path: str,
    elements: list[dict],
    method: str = "auto",
) -> list[dict]:
    """检测图片中各元素的 bbox。

    Args:
        image_path: PNG 图片路径
        elements: 元素列表（含 id, description）
        method: "auto"=Vision优先/OpenCV降级, "vision"=仅Vision, "opencv"=仅OpenCV

    Returns:
        elements 列表，补全 bbox 字段
    """
    if not os.path.exists(image_path):
        print(f"  [ERR] 图片不存在: {image_path}")
        return _fallback_split(elements)

    try:
        from PIL import Image as PILImage
        with PILImage.open(image_path) as im:
            img_w, img_h = im.size
    except Exception:
        img_w, img_h = 1920, 1080

    print(f"  图片: {image_path} ({img_w}×{img_h}), {len(elements)} 个元素")

    if not elements:
        return []

    # 只有一个元素 → 全画布
    if len(elements) == 1:
        return [{**elements[0], "bbox": {"x": 0, "y": 0, "w": img_w, "h": img_h}}]

    result = None

    # 方案 A: Vision API
    if method in ("auto", "vision"):
        result = _detect_vision(image_path, elements, img_w, img_h)

    # 方案 B: OpenCV 降级
    if result is None and method in ("auto", "opencv"):
        print(f"  [OpenCV] 使用图像处理检测内容区域...")
        result = _detect_opencv(image_path, elements, img_w, img_h)

    # 最终降级
    if result is None:
        print(f"  [FALLBACK] 垂直等分画布")
        result = _fallback_split(elements, img_w, img_h)

    return result


# ── Batch Processing ──

def process_all_scenes(
    storyboard_path: str,
    images_dir: str,
    output_path: str,
    review: bool = False,
    method: str = "auto",
) -> dict:
    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    scenes = storyboard.get("scenes", [])
    print(f"\n  检测 {len(scenes)} 个场景的元素 bbox...")

    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        image_path = os.path.join(images_dir, f"{scene_id}.png")
        elements = scene.get("elements", [])
        print(f"\n  场景 {i+1}/{len(scenes)}: {scene_id}")
        if not elements:
            print(f"    [SKIP] 无元素定义")
            continue
        if not os.path.exists(image_path):
            print(f"    [WARN] 图片不存在: {image_path}")
            continue

        detected = detect_element_bboxes(image_path, elements, method=method)
        scene["elements"] = detected

        if review:
            preview_dir = os.path.join(os.path.dirname(output_path), "preview")
            os.makedirs(preview_dir, exist_ok=True)
            draw_bbox_preview(image_path, detected, os.path.join(preview_dir, f"{scene_id}_bbox.png"))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    print(f"\n  完整 storyboard: {output_path}")
    return storyboard


def main():
    import argparse
    parser = argparse.ArgumentParser(description="元素 bbox 检测")
    parser.add_argument("--storyboard", "-s", required=True)
    parser.add_argument("--images-dir", "-i")
    parser.add_argument("--output", "-o")
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--method", choices=["auto", "vision", "opencv"], default="auto",
                        help="检测方法: auto=Vision优先/OpenCV降级")
    args = parser.parse_args()

    with open(args.storyboard, encoding="utf-8") as f:
        sb = json.load(f)
    topic = sb.get("meta", {}).get("topic", "untitled")
    output_dir = Path(args.output) if args.output else Path(__file__).resolve().parent.parent / "output" / topic
    images_dir = args.images_dir or str(output_dir / "images")
    output_path = args.output or str(output_dir / "storyboard-complete.json")

    process_all_scenes(args.storyboard, images_dir, output_path, review=args.review, method=args.method)


if __name__ == "__main__":
    main()
