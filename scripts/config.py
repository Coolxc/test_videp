#!/usr/bin/env python3
"""项目级配置：路径解析、常量、工具函数。所有脚本从此导入。"""

import os
from pathlib import Path


# ── 项目根目录 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 外部引擎路径（优先读环境变量，便于不同部署环境适配）──
ENGINE_DIR = Path(os.environ.get(
    "WHITEBOARD_ENGINE_DIR",
    str(PROJECT_ROOT / "whiteboard-video-workflow" / "whiteboard-animation")
))
ENGINE_SCRIPTS_DIR = ENGINE_DIR / "scripts"
ENGINE_HAND_PATH = ENGINE_DIR / "assets" / "drawing-hand.png"

# ── Prompt 模版仓库路径（兼容旧版 whiteboard-video 引用）──
WORKFLOW_DIR = Path(os.environ.get(
    "WHITEBOARD_WORKFLOW_DIR",
    str(PROJECT_ROOT / "whiteboard-video")
))
ENGINE_WORKFLOW_DIR = Path(os.environ.get(
    "WHITEBOARD_ENGINE_WORKFLOW_DIR",
    str(PROJECT_ROOT / "whiteboard-video-workflow" / "whiteboard-video-workflow")
))

# ── 视觉常量 ──
BACKGROUND_HEX = "#F6F1E3"
BACKGROUND_BGR = (227, 241, 246)  # OpenCV BGR 格式
BACKGROUND_RGB = (246, 241, 227)


# ── 图片命名 ──
def get_image_filename(scene_id: str) -> str:
    """标准图片文件名。全管线唯一命名规则。"""
    return f"{scene_id}.png"


def get_output_dir(storyboard: dict) -> Path:
    """从 storyboard meta 计算输出目录。"""
    import time
    topic = storyboard.get("meta", {}).get("topic", "untitled")
    # 清理不安全字符
    safe_topic = "".join(c if c.isalnum() or c in "-_" else "-" for c in topic)
    return PROJECT_ROOT / "output" / f"{safe_topic}-{time.strftime('%Y%m%d')}"


def validate_engine():
    """启动时检查引擎是否可用。"""
    errors = []
    if not ENGINE_DIR.exists():
        errors.append(f"动画引擎目录不存在: {ENGINE_DIR}")
    if not (ENGINE_SCRIPTS_DIR / "generate_whiteboard.py").exists():
        errors.append(f"引擎脚本不存在: {ENGINE_SCRIPTS_DIR / 'generate_whiteboard.py'}")
    if not ENGINE_HAND_PATH.exists():
        errors.append(f"画手素材不存在: {ENGINE_HAND_PATH}")
    return errors
