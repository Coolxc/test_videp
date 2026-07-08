#!/usr/bin/env python3
"""
sfx_library.py
关键词与音效素材映射管理。
"""

import os
from pathlib import Path

# --- 音效映射表 (基于用户建议扩展) ---
SFX_MAP = {
    "敲门": "knock.wav",
    "门": "door_click.wav",
    "危险": "tension_drone.wav",
    "紧张": "tension_drone.wav",
    "心跳": "heartbeat.wav",
    "写字": "pencil_scratch.wav",
    "检查": "click.wav",
    "报警": "siren_short.wav"
}

# --- 环境音映射表 ---
AMBIENT_MAP = {
    "default": "room_ambience.wav",
    "tense": "tense_ambient.wav",
    "night": "night_crickets.wav"
}

def get_sfx_for_text(text, assets_dir):
    """
    根据文本返回匹配的音效路径列表。
    """
    matches = []
    assets_path = Path(assets_dir)
    for keyword, filename in SFX_MAP.items():
        if keyword in text:
            full_path = assets_path / filename
            if full_path.exists():
                matches.append(str(full_path))
    return matches

def get_ambient_path(mood, assets_dir):
    """
    根据情绪返回背景音路径。
    """
    assets_path = Path(assets_dir)
    filename = AMBIENT_MAP.get(mood, AMBIENT_MAP["default"])
    full_path = assets_path / filename
    return str(full_path) if full_path.exists() else None
