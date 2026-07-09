#!/usr/bin/env python3
"""
deploy_resources.py - Copy generated assets to remotion-project/ for SVG pipeline.

Copies:
  - SVG data (svg-data.json) → public/svg-data/ + src/
  - TTS audio files → public/audio/
  - SFX files → public/assets/sfx/
  - BGM → public/bgm.mp3 (if not exists)
  - Writing hand PNG → public/assets/
  - Scene config + timeline → public/ + src/
"""

import json
import os
import shutil
from pathlib import Path

from config import PROJECT_ROOT, ENGINE_HAND_PATH, WORKFLOW_DIR


def deploy_resources(storyboard_path: str, output_dir: str = None,
                      copy_animations: bool = True,
                      copy_audio: bool = True,
                      copy_sfx: bool = True,
                      timeline_path: str = None):
    """Deploy generated resources to remotion-project/."""
    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    meta = storyboard.get("meta", {})
    topic = meta.get("topic", "untitled")

    if output_dir is None:
        from config import get_output_dir
        output_dir = str(get_output_dir(storyboard))

    remotion_public = PROJECT_ROOT / "remotion-project" / "public"
    remotion_src = PROJECT_ROOT / "remotion-project" / "src"
    os.makedirs(remotion_public, exist_ok=True)

    # ── 1. SVG 数据（替代旧版 MP4 动画）──
    svg_src_dir = Path(output_dir) / "svg_data"
    svg_dst_dir = remotion_public / "svg-data"
    os.makedirs(svg_dst_dir, exist_ok=True)

    if svg_src_dir.exists():
        for f in svg_src_dir.glob("*.json"):
            shutil.copy2(f, svg_dst_dir / f.name)
            print(f"  SVG data: {f.name}")
    else:
        print(f"  [WARN] No SVG data dir: {svg_src_dir}")

    # 复制 svg-data.json 到 src/ 用于 TypeScript import
    svg_merged_src = svg_src_dir / "svg-data.json"
    if svg_merged_src.exists():
        shutil.copy2(svg_merged_src, remotion_src / "svg-data.json")
        print(f"  SVG data (src): svg-data.json")

    # ── 2. Audio ──
    if copy_audio:
        audio_src = Path(output_dir) / "audio"
        audio_dst = remotion_public / "audio"
        os.makedirs(audio_dst, exist_ok=True)

        if audio_src.exists():
            for f in audio_src.glob("*.wav"):
                shutil.copy2(f, audio_dst / f.name)
                print(f"  Audio: {f.name}")

        # BGM: copy from whiteboard-video if not exists
        bgm_dst = remotion_public / "bgm.mp3"
        if not bgm_dst.exists():
            bgm_src = WORKFLOW_DIR / "remotion-project" / "public" / "bgm.mp3"
            if bgm_src.exists():
                shutil.copy2(bgm_src, bgm_dst)
                print(f"  BGM: copied from whiteboard-video")

    # ── 3. SFX ──
    if copy_sfx:
        sfx_dst = remotion_public / "assets" / "sfx"
        os.makedirs(sfx_dst, exist_ok=True)
        for name in ("pen_sketch.mp3",):
            if not (sfx_dst / name).exists():
                print(f"  [WARN] SFX not found: {name}")

    # ── 4. Writing hand ──
    hand_dst = remotion_public / "assets" / "writing-hand-small.png"
    if not hand_dst.exists():
        hand_src = ENGINE_HAND_PATH
        if hand_src.exists():
            import cv2
            img = cv2.imread(str(hand_src), cv2.IMREAD_UNCHANGED)
            if img is not None:
                h, w = img.shape[:2]
                scale = 200 / max(h, w)
                new_w, new_h = int(w * scale), int(h * scale)
                small = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                cv2.imwrite(str(hand_dst), small)
                print(f"  Writing hand: {hand_dst}")

    # ── 5. Fonts ──
    fonts_dst = remotion_public / "fonts"
    os.makedirs(fonts_dst, exist_ok=True)

    # ── 6. Update scene-config.json + timeline.json ──
    _update_scene_config(storyboard, remotion_public, timeline_path=timeline_path)

    print(f"\n  Resources deployed to: {remotion_public}")


def _update_scene_config(storyboard: dict, remotion_public: Path,
                          timeline_path: str = None):
    """Generate scene-config.json and timeline.json for Remotion consumption."""
    scenes_out = []
    for scene in storyboard.get("scenes", []):
        scenes_out.append({
            "id": scene["id"],
            "imagePrompt": scene.get("imagePrompt", ""),
            "voiceText": scene.get("voiceText", ""),
            "duration": scene.get("duration", None),
            "textOverlay": scene.get("textOverlay", None),
            "elements": scene.get("elements", []),
        })

    config = {
        "meta": storyboard.get("meta", {}),
        "scenes": scenes_out,
    }

    # Copy to public/ for static access
    config_path_public = remotion_public / "scene-config.json"
    with open(config_path_public, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"  Scene config: {config_path_public}")

    # Copy to src/ for TypeScript imports
    config_path_src = remotion_public.parent / "src" / "scene-config.json"
    with open(config_path_src, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"  Scene config (src): {config_path_src}")

    # Copy timeline.json to both public/ and src/
    remotion_src = remotion_public.parent / "src"
    if timeline_path and os.path.exists(timeline_path):
        shutil.copy2(timeline_path, remotion_public / "timeline.json")
        shutil.copy2(timeline_path, remotion_src / "timeline.json")
        print(f"  Timeline deployed: {timeline_path}")
    else:
        timeline_public = remotion_public / "timeline.json"
        if timeline_public.exists():
            shutil.copy2(timeline_public, remotion_src / "timeline.json")
            print(f"  Timeline (src): {remotion_src / 'timeline.json'}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Deploy resources to Remotion public dir")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--output-dir", "-o", help="Pipeline output directory")
    parser.add_argument("--no-audio", action="store_true", help="Skip audio copy")
    args = parser.parse_args()

    deploy_resources(
        args.storyboard,
        output_dir=args.output_dir,
        copy_animations=False,  # SVG mode — no MP4
        copy_audio=not args.no_audio,
    )
