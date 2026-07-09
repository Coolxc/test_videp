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


from config import PROJECT_ROOT, BACKGROUND_BGR as _BACKGROUND_BGR


def normalize_image_size(image_path: str, target_w: int = 1920, target_h: int = 1080) -> bool:
    """等比缩放图片到目标尺寸，白色 padding 填充。返回 True 已修改。"""
    img = cv2.imread(image_path)
    if img is None:
        return False

    h, w = img.shape[:2]
    if w == target_w and h == target_h:
        return False

    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

    canvas = np.full((target_h, target_w, 3), 255, dtype=np.uint8)
    y_off = (target_h - new_h) // 2
    x_off = (target_w - new_w) // 2
    canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
    cv2.imwrite(image_path, canvas)
    return True


def find_and_normalize_image(images_dir: str, scene_id: str):
    """查找场景图片，支持大小写不敏感、多后缀、自动重命名。

    查找优先级：
    1. 精确匹配: {scene_id}.png
    2. 大小写不敏感匹配: {Scene_ID}.png, {SCENE_ID}.PNG 等
    3. 替代后缀: .jpg, .jpeg, .webp
    4. 包含 scene_id 的文件（如 "scene1_seedream.png"）

    找到后自动转换为标准格式 {scene_id}.png 并返回路径。
    """
    from config import get_image_filename
    canonical = get_image_filename(scene_id)  # "scene1.png"
    canonical_path = os.path.join(images_dir, canonical)

    # 1. 精确匹配
    if os.path.exists(canonical_path):
        return canonical_path

    # 2-4. 搜索目录
    if not os.path.isdir(images_dir):
        return None

    candidates = []
    for f in os.listdir(images_dir):
        fname_lower = f.lower()
        sid_lower = scene_id.lower()

        # 大小写不敏感的精确匹配
        if fname_lower == canonical.lower():
            candidates.insert(0, f)  # 最高优先级
            continue

        # 替代后缀
        name_part = os.path.splitext(fname_lower)[0]
        if name_part == sid_lower and fname_lower.endswith(
            (".png", ".jpg", ".jpeg", ".webp")
        ):
            candidates.append(f)
            continue

        # 包含 scene_id 的文件
        if sid_lower in fname_lower and fname_lower.endswith(
            (".png", ".jpg", ".jpeg", ".webp")
        ):
            candidates.append(f)

    if not candidates:
        return None

    source_file = candidates[0]
    source_path = os.path.join(images_dir, source_file)

    # 自动转换并重命名
    if source_file != canonical:
        ext = os.path.splitext(source_file)[1].lower()
        if ext in (".webp", ".jpg", ".jpeg"):
            img = cv2.imread(source_path)
            if img is not None:
                cv2.imwrite(canonical_path, img)
                print(f"  [AUTO] 转换 {source_file} -> {canonical}")
                return canonical_path
        else:
            os.rename(source_path, canonical_path)
            print(f"  [AUTO] 重命名 {source_file} -> {canonical}")
            return canonical_path

    return canonical_path


def validate_images(storyboard: dict, images_dir: str,
                     strict: bool = True) -> list[str]:
    """Validate all scene images. strict=True 时缺图直接报错。

    Returns list of (error/warning) messages.
    """
    messages = []
    scenes = storyboard.get("scenes", [])
    meta = storyboard.get("meta", {})

    expected_w = meta.get("width", 1920)
    expected_h = meta.get("height", 1080)

    histograms = []
    missing = []

    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        img_path = find_and_normalize_image(images_dir, scene_id)

        # 1. Check file exists
        if img_path is None:
            missing.append(scene_id)
            messages.append(f"[ERR] Scene '{scene_id}': image not found")
            continue

        # Read image
        img = cv2.imread(img_path)
        if img is None:
            messages.append(f"[ERR] Scene '{scene_id}': cannot read image")
            continue

        # Normalize to 1920x1080
        if normalize_image_size(img_path):
            messages.append(f"[AUTO] Scene '{scene_id}': resized to 1920x1080")
            img = cv2.imread(img_path)  # Re-read after resize

        h, w = img.shape[:2]

        # 2. Check size
        min_dim = min(w, h)
        if min_dim < 512:
            messages.append(f"[WARN] Scene '{scene_id}': image too small ({w}x{h}, min 512px recommended)")

        # 3. Check background color (pure white)
        corner_pixels = [
            img[5, 5], img[5, -5], img[-5, 5], img[-5, -5],
            img[h//2, 5], img[h//2, -5],
        ]
        avg_corner = np.mean(corner_pixels, axis=0)
        is_pure_white = np.all(avg_corner > 245)
        if not is_pure_white:
            messages.append(f"[WARN] Scene '{scene_id}': background may not be pure white "
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

    if missing and strict:
        from config import get_image_filename
        expected = [get_image_filename(sid) for sid in missing]
        raise FileNotFoundError(
            f"\n{'='*60}\n"
            f"  缺少 {len(missing)} 个场景的图片！\n"
            f"  缺失场景: {missing}\n"
            f"  期望文件: {expected}\n"
            f"  图片目录: {images_dir}\n"
            f"\n"
            f"  请根据 prompts.md 中的指引生成图片，\n"
            f"  并保存为上述文件名放入图片目录。\n"
            f"{'='*60}"
        )

    return messages


def fix_background_color(images_dir: str, target_bgr=(255, 255, 255),
                          tolerance: int = 30):
    """内容感知的背景色修复。仅替换与图片边缘连通的近白色区域。

    原理：真正的背景区域与图片边缘连通（可以从边缘泛洪到达），
    而画面内的浅色内容被其他内容包围，不与边缘连通。
    """
    import glob
    changed = False
    for img_path in glob.glob(os.path.join(images_dir, "*.png")) + glob.glob(os.path.join(images_dir, "*.jpg")):
        img = cv2.imread(img_path)
        if img is None:
            continue

        bg_mask = _detect_background_mask(img, tolerance)
        if bg_mask is None or bg_mask.sum() == 0:
            continue

        # 形态学腐蚀：防止侵蚀到内容边缘
        kernel = np.ones((3, 3), np.uint8)
        bg_mask = cv2.erode(bg_mask, kernel, iterations=2)

        # 仅替换确认的背景像素
        if bg_mask.sum() > 0:
            img[bg_mask > 0] = np.array(target_bgr, dtype=np.uint8)
            cv2.imwrite(img_path, img)
            changed = True
            print(f"  Fixed background: {os.path.basename(img_path)}")

    return changed


def _detect_background_mask(img, tolerance=30):
    """通过边缘泛洪检测背景区域。

    1. 采样图片四角的颜色，取中位数作为疑似背景色
    2. 创建颜色接近度掩码（与背景色差异 < tolerance 的像素）
    3. 从四个角开始泛洪填充，只标记与边缘连通的近背景色像素
    """
    h, w = img.shape[:2]

    # 采样四角 5x5 区域的平均色
    corners = [
        img[0:5, 0:5],          # 左上
        img[0:5, w-5:w],        # 右上
        img[h-5:h, 0:5],        # 左下
        img[h-5:h, w-5:w],      # 右下
    ]
    corner_colors = [c.reshape(-1, 3).mean(axis=0) for c in corners]
    bg_color = np.median(corner_colors, axis=0).astype(np.uint8)

    # 检查四角是否一致（如果差异过大，可能不是纯色背景）
    diffs = [np.linalg.norm(c - bg_color) for c in corner_colors]
    if max(diffs) > tolerance * 2:
        return None  # 非纯色背景，不做修复

    # 颜色接近度掩码
    lower = np.clip(bg_color.astype(int) - tolerance, 0, 255).astype(np.uint8)
    upper = np.clip(bg_color.astype(int) + tolerance, 0, 255).astype(np.uint8)
    color_mask = cv2.inRange(img, lower, upper)

    # 从四角泛洪填充
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    seed_points = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    for seed in seed_points:
        # 只在 color_mask 为 255 的区域泛洪
        if color_mask[seed[1], seed[0]] > 0:
            cv2.floodFill(
                color_mask, flood_mask, seed,
                newVal=128,  # 标记已访问
                loDiff=(tolerance,) * 3,
                upDiff=(tolerance,) * 3,
                flags=cv2.FLOODFILL_MASK_ONLY | (255 << 8),
            )

    # flood_mask 的有效区域（去掉 1px 边框）
    result = flood_mask[1:-1, 1:-1]
    return (result > 0).astype(np.uint8) * 255


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Validate scene images")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--images-dir", "-i", help="Path to images directory (default: output/{topic}/images)")
    parser.add_argument("--fix-bg", action="store_true", help="Auto-fix background colors to pure white")
    args = parser.parse_args()

    with open(args.storyboard, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    topic = storyboard.get("meta", {}).get("topic", "untitled")
    if not args.images_dir:
        args.images_dir = str(PROJECT_ROOT / "output" / topic / "images")

    if args.fix_bg:
        fix_background_color(args.images_dir)

    validate_images(storyboard, args.images_dir)
