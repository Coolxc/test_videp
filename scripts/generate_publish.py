#!/usr/bin/env python3
"""
generate_publish.py - Generate publishing copy for the video.

Produces publish.md with platform-optimized descriptions, titles, and tags
for Bilibili, YouTube, Xiaohongshu, and Douyin.
"""

import json
import os
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def generate_publish(storyboard_path: str, output_path: str = None) -> str:
    """Generate publish.md with platform-specific publishing copy."""
    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    meta = storyboard.get("meta", {})
    scenes = storyboard.get("scenes", [])

    title = meta.get("title", "Untitled")
    topic = meta.get("topic", "untitled")

    # Collect key topics from scenes
    topics_set = set()
    for scene in scenes:
        prompt = scene.get("imagePrompt", "")
        # Extract key nouns (simple heuristic)
        for word in prompt.split():
            if len(word) > 2 and word[0].isupper():
                topics_set.add(word)

    # Estimate video length
    total_chars = sum(len(s.get("voiceText", "")) for s in scenes)
    est_duration_s = total_chars / 4.0 + 3 * len(scenes)
    est_minutes = int(est_duration_s // 60)
    est_seconds = int(est_duration_s % 60)

    lines = []
    lines.append(f"# Publishing Copy: {title}")
    lines.append(f"")
    lines.append(f"**Estimated duration:** {est_minutes}m{est_seconds}s")
    lines.append(f"**Scenes:** {len(scenes)}")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # Bilibili
    lines.append(f"## Bilibili")
    lines.append(f"")
    lines.append(f"**Title:** {title} | 知识分享")
    lines.append(f"")
    lines.append(f"**Description:**")
    lines.append(f"{' '.join(s.get('voiceText', '') for s in scenes[:3])}...")
    lines.append(f"")
    lines.append(f"**Tags:** {topic}, 知识分享, 手绘视频, 白板动画, 科普")
    lines.append(f"")

    # YouTube
    lines.append(f"## YouTube")
    lines.append(f"")
    lines.append(f"**Title:** {title}")
    lines.append(f"")
    lines.append(f"**Description:**")
    for scene in scenes:
        if scene.get("voiceText"):
            lines.append(f"- {scene['voiceText']}")
    lines.append(f"")
    lines.append(f"**Tags:** #whitboard #animation #{topic} #education #knowledge")
    lines.append(f"")

    # Xiaohongshu
    lines.append(f"## Xiaohongshu")
    lines.append(f"")
    lines.append(f"**Title:** {title} ｜ 一分钟看懂")
    lines.append(f"")
    lines.append(f"**Body:**")
    hooks = scenes[0].get("voiceText", "") if scenes else ""
    lines.append(f"{hooks}")
    lines.append(f"")
    for s in scenes:
        if s.get("voiceText"):
            lines.append(f"✨ {s['voiceText']}")
    lines.append(f"")
    lines.append(f"#知识分享 #{topic} #手绘 #干货")
    lines.append(f"")

    # Douyin
    lines.append(f"## Douyin")
    lines.append(f"")
    lines.append(f"**Title:** {title}")
    lines.append(f"")
    first_line = scenes[0].get("voiceText", "") if scenes else ""
    lines.append(f"**Caption:** {first_line}")
    lines.append(f"#{topic} #知识分享 #手绘动画")

    publish_text = "\n".join(lines)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(publish_text)
        print(f"  Publish copy: {output_path}")

    return publish_text


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate publishing copy")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--output", "-o", help="Output publish.md path")
    args = parser.parse_args()

    with open(args.storyboard) as f:
        sb = json.load(f)
    topic = sb.get("meta", {}).get("topic", "untitled")
    output = args.output or str(_PROJECT_ROOT / "output" / topic / "publish.md")

    generate_publish(args.storyboard, output)
