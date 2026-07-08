#!/usr/bin/env python3
"""
render_hook.py V3 (Viral Masterpiece)

支持三种爆款模板：
1. black (Default): 黑底背景 + 黄白大字 + Top 1/3 布局
2. warning: 红底背景 + 白色大字 (极度警示)
3. image: 场景模糊背景 + 黄白大字

支持关键词高亮：使用 *关键词* 语法
"""

import argparse
import cv2
import numpy as np
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def create_bg(mode, width, height, image_path=None, blur_k=(91, 91)):
    if mode == "warning":
        # 警示红
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (0, 0, 180) # BGR
        return frame
    elif mode == "image" and image_path:
        img = cv2.imread(str(image_path))
        if img is not None:
            img_resized = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
            img_blurred = cv2.GaussianBlur(img_resized, blur_k, 0)
            return cv2.addWeighted(img_blurred, 0.5, np.zeros_like(img_blurred), 0, 0)
    
    # Default Black
    return np.zeros((height, width, 3), dtype=np.uint8)

def draw_viral_text(cv2_img, text, font_size=160):
    img_pil = Image.fromarray(cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    w, h = img_pil.size
    
    # 字体加载
    font_paths = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Light.ttc"]
    font = next((ImageFont.truetype(p, font_size) for p in font_paths if Path(p).exists()), ImageFont.load_default())
    
    # 解析高亮关键字 (e.g., *别开门*)
    # 简单实现：将文本拆分为片段，记录哪些片段需要黄色
    parts = []
    plain_text = ""
    last_end = 0
    for match in re.finditer(r"\*(.*?)\*", text):
        # Normal text before match
        if match.start() > last_end:
            parts.append({"text": text[last_end:match.start()], "color": (255, 255, 255)})
            plain_text += text[last_end:match.start()]
        # Highlighted text
        parts.append({"text": match.group(1), "color": (255, 255, 0)})
        plain_text += match.group(1)
        last_end = match.end()
    if last_end < len(text):
        parts.append({"text": text[last_end:], "color": (255, 255, 255)})
        plain_text += text[last_end:]
    
    # 如果没有星号标记，则默认整行白字
    if not parts:
        parts = [{"text": text, "color": (255, 255, 255)}]
        plain_text = text

    # 计算总宽度以居中
    total_w = 0
    for p in parts:
        left, top, right, bottom = draw.textbbox((0, 0), p["text"], font=font)
        p["w"] = right - left
        p["h"] = bottom - top
        total_w += p["w"]
    
    # 限制字号：如果文字太宽，自动缩小
    max_w = w * 0.85
    if total_w > max_w:
        scale = max_w / total_w
        font_size = int(font_size * scale)
        return draw_viral_text(cv2_img, text, font_size) # 递归调整

    # 绘制位置：黄金 Top 1/3 (垂直 30% 处)
    curr_x = (w - total_w) // 2
    curr_y = int(h * 0.3)
    
    for p in parts:
        # 描边
        for offset in [(-4, -4), (4, -4), (-4, 4), (4, 4)]:
            draw.text((curr_x + offset[0], curr_y + offset[1]), p["text"], font=font, fill=(0, 0, 0))
        # 主体
        draw.text((curr_x, curr_y), p["text"], font=font, fill=p["color"])
        curr_x += p["w"]

    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True, help="Hook text")
    parser.add_argument("--mode", choices=["black", "warning", "image"], default="black")
    parser.add_argument("--bg-image", help="Background for image mode")
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=1080) # Shorts default 9:16
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--duration", type=int, default=2)
    
    args = parser.parse_args()
    
    frame = create_bg(args.mode, args.width, args.height, args.bg_image)
    frame = draw_viral_text(frame, args.text)
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(args.output, fourcc, args.fps, (args.width, args.height))
    for _ in range(args.fps * args.duration):
        out.write(frame)
    out.release()
    print(f"Viral Hook Rendered: {args.output}")

if __name__ == "__main__":
    main()
