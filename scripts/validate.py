#!/usr/bin/env python3
"""
validate.py - Environment check + storyboard schema validation.

Checks:
- Python dependencies (opencv-python, numpy, av, scipy, pydub)
- ffmpeg / ffprobe availability
- Animation engine directory + assets
- storyboard.json schema conformance
- Optional: API keys for TTS
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _PROJECT_ROOT / "whiteboard-video-workflow" / "whiteboard-animation"


def check_python_deps() -> list[str]:
    errors = []
    required = [
        ("cv2", "opencv-python"),
        ("numpy", "numpy"),
        ("pydub", "pydub"),
    ]
    optional = [("av", "av"), ("scipy", "scipy")]

    for mod_name, pip_name in required:
        try:
            __import__(mod_name)
        except ImportError:
            errors.append(f"Missing: {pip_name} (pip install {pip_name})")

    for mod_name, pip_name in optional:
        try:
            __import__(mod_name)
        except ImportError:
            print(f"  [WARN] Optional dependency missing: {pip_name}")

    return errors


def check_ffmpeg() -> list[str]:
    errors = []
    for cmd in ("ffmpeg", "ffprobe"):
        if shutil.which(cmd) is None:
            errors.append(f"Missing: {cmd} not found in PATH")
        else:
            try:
                subprocess.run([cmd, "-version"], capture_output=True, timeout=5)
            except Exception as e:
                errors.append(f"  {cmd} error: {e}")
    return errors


def check_engine() -> list[str]:
    errors = []
    if not _ENGINE_DIR.exists():
        errors.append(f"Animation engine not found: {_ENGINE_DIR}")
        return errors

    scripts_dir = _ENGINE_DIR / "scripts"
    if not (scripts_dir / "generate_whiteboard.py").exists():
        errors.append(f"Missing: {scripts_dir / 'generate_whiteboard.py'}")

    assets_dir = _ENGINE_DIR / "assets"
    if not (assets_dir / "drawing-hand.png").exists():
        errors.append(f"Missing: {assets_dir / 'drawing-hand.png'}")

    return errors


def validate_storyboard_schema(sb: dict) -> list[str]:
    errors = []

    if "meta" not in sb:
        errors.append("Missing 'meta' section")
        return errors

    meta = sb["meta"]
    if "title" not in meta:
        errors.append("meta.title is required")
    if "fps" not in meta:
        errors.append("meta.fps is required")
    if "scenes" not in sb or not isinstance(sb["scenes"], list):
        errors.append("'scenes' must be a non-empty array")
        return errors

    for i, scene in enumerate(sb["scenes"]):
        prefix = f"scenes[{i}]"
        if "id" not in scene:
            errors.append(f"{prefix}: 'id' is required")
        if "imagePrompt" not in scene:
            errors.append(f"{prefix}: 'imagePrompt' is required")

        elements = scene.get("elements")
        if elements is not None:
            for j, elem in enumerate(elements):
                ep = f"{prefix}.elements[{j}]"
                if "id" not in elem:
                    errors.append(f"{ep}: 'id' is required")
                if "bbox" in elem:
                    bbox = elem["bbox"]
                    for k in ("x", "y", "w", "h"):
                        if k not in bbox:
                            errors.append(f"{ep}.bbox: '{k}' is required")

    return errors


def check_tts_keys() -> list[str]:
    errors = []
    # Check env vars or .env file
    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)

    if not os.environ.get("TENCENT_SECRET_ID"):
        errors.append("TENCENT_SECRET_ID not found (required for --mode full)")
    if not os.environ.get("TENCENT_SECRET_KEY"):
        errors.append("TENCENT_SECRET_KEY not found (required for --mode full)")

    return errors


def run_checks(storyboard_path: str = None, check_tts: bool = False) -> bool:
    all_errors = []

    print("=== Environment Check ===")

    print("\n[1/4] Python dependencies...")
    all_errors.extend(check_python_deps())

    print("\n[2/4] ffmpeg/ffprobe...")
    all_errors.extend(check_ffmpeg())

    print("\n[3/4] Animation engine...")
    all_errors.extend(check_engine())

    if storyboard_path:
        print(f"\n[4/4] Storyboard schema: {storyboard_path}")
        try:
            with open(storyboard_path, "r", encoding="utf-8") as f:
                sb = json.load(f)
            all_errors.extend(validate_storyboard_schema(sb))
        except Exception as e:
            all_errors.append(f"Cannot read storyboard: {e}")

    if check_tts:
        print("\n  TTS keys...")
        all_errors.extend(check_tts_keys())

    if all_errors:
        print(f"\n{'='*50}")
        print(f"Found {len(all_errors)} issue(s):")
        for e in all_errors:
            print(f"  [ERR] {e}")
        print(f"{'='*50}")
        return False

    print("\n  All checks passed!")
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Validate environment and storyboard")
    parser.add_argument("--storyboard", help="Path to storyboard.json for schema validation")
    parser.add_argument("--check-tts", action="store_true", help="Also check TTS API keys")
    args = parser.parse_args()

    success = run_checks(args.storyboard, args.check_tts)
    sys.exit(0 if success else 1)
