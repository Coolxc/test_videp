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

from config import PROJECT_ROOT, validate_engine as config_validate_engine


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

    # Vectorization deps
    for mod_name, pip_name in [("svgpathtools", "svgpathtools")]:
        try:
            __import__(mod_name)
        except ImportError:
            errors.append(f"Missing: {pip_name} (pip install {pip_name})")

    return errors


def check_ffmpeg() -> list[str]:
    """ffmpeg 检查降级为警告（SVG 管线不直接依赖，但 Remotion 渲染时需要）。"""
    warnings = []
    for cmd in ("ffmpeg",):
        if shutil.which(cmd) is None:
            warnings.append(f"ffmpeg 未安装（Remotion 渲染时需要）")
        else:
            try:
                subprocess.run([cmd, "-version"], capture_output=True, timeout=5)
            except Exception as e:
                warnings.append(f"  {cmd} error: {e}")
    return warnings  # 返回 warnings 而非 errors


def check_engine() -> list[str]:
    # SVG 管线不再需要旧引擎
    return []


def check_potrace() -> list[str]:
    """检查 potrace CLI 是否可用。"""
    errors = []
    if shutil.which("potrace") is None:
        errors.append("potrace 未安装。运行: sudo apt install potrace")
    else:
        try:
            subprocess.run(["potrace", "--version"], capture_output=True, timeout=5)
        except Exception as e:
            errors.append(f"potrace 错误: {e}")
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

        # imagePrompt 或 voiceText 至少有一个
        if not scene.get("imagePrompt") and not scene.get("voiceText"):
            errors.append(f"{prefix}: 至少需要 imagePrompt 或 voiceText")

        # 验证 imageName 格式（如果指定）
        if scene.get("imageName"):
            name = scene["imageName"]
            if not name.endswith(".png"):
                errors.append(f"{prefix}: imageName 必须以 .png 结尾, 当前: {name}")

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
                # drawStrategy 校验
                VALID_DRAW_STRATEGIES = {
                    "spatial_walk", "top_down", "bottom_up",
                    "left_right", "outline_first", "center_out",
                }
                ds = elem.get("drawStrategy")
                if ds and ds not in VALID_DRAW_STRATEGIES:
                    errors.append(f"{ep}: unknown drawStrategy '{ds}'")

    return errors


def check_llm_keys() -> list[str]:
    """Check LLM API key availability. Non-fatal — prints warning if missing."""
    warnings = []

    # 优先从 .env 加载（同 check_tts_keys 的做法）
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            pass  # dotenv 未安装，后面会报 key 缺失

    if not os.environ.get("DEEPSEEK_API_KEY"):
        warnings.append(
            "DEEPSEEK_API_KEY 未设置，prompt 生成将使用静态模版（质量降低）"
        )
    return warnings


def check_tts_keys() -> list[str]:
    errors = []
    # Check env vars or .env file
    env_path = PROJECT_ROOT / ".env"
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
    all_warnings = []

    print("=== Environment Check (SVG Pipeline) ===")

    print("\n[1/4] Python dependencies (svgpathtools)...")
    all_errors.extend(check_python_deps())

    print("\n[2/4] ffmpeg + potrace...")
    all_warnings.extend(check_ffmpeg())
    for w in all_warnings:
        print(f"  [WARN] {w}")
    all_errors.extend(check_potrace())

    print("\n[3/4] Engine assets...")
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

    print("\n  LLM keys...")
    llm_warnings = check_llm_keys()
    for w in llm_warnings:
        print(f"  [WARN] {w}")

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
