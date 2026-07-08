#!/usr/bin/env python3
"""
mixer.py
Shorts Audio Engine - Multi-track Mixing Module
支持人声、背景环境音、瞬时音效 (SFX) 的三层混音。
"""

import os
from pydub import AudioSegment
from pathlib import Path
import random

def mix_audio_layers(voice_segments, total_duration_ms, ambient_path=None, sfx_list=None, output_path="final_audio.mp3"):
    """
    voice_segments: list of dict {"path": str, "start_ms": int, "volume_delta": float}
    total_duration_ms: int
    ambient_path: str (背景循环音)
    sfx_list: list of dict {"path": str, "start_ms": int, "volume_delta": float}
    """
    
    # 1. 创建空白画布 (Silent base)
    final_audio = AudioSegment.silent(duration=total_duration_ms)
    
    # 2. 混合背景环境音 (Ambient Layer)
    if ambient_path and os.path.exists(ambient_path):
        ambient = AudioSegment.from_file(ambient_path)
        # 循环环境音直到覆盖总长度
        loops = (total_duration_ms // len(ambient)) + 1
        ambient_loop = (ambient * loops)[:total_duration_ms]
        # 默认降低背景音量 (建议 -20dB 到 -30dB)
        final_audio = final_audio.overlay(ambient_loop - 25)
    
    # 3. 混合主语音 (Voice Layer)
    for v in voice_segments:
        if not os.path.exists(v["path"]): continue
        voice = AudioSegment.from_file(v["path"])
        # 自带一点音量随机波动 (增加呼吸感)
        volume = v.get("volume_delta", 0) + random.uniform(-1.0, 1.0)
        final_audio = final_audio.overlay(voice + volume, position=v["start_ms"])
        
    # 4. 混合瞬时音效 (SFX Layer)
    if sfx_list:
        for s in sfx_list:
            if not os.path.exists(s["path"]): continue
            sfx = AudioSegment.from_file(s["path"])
            # SFX 通常稍微柔和一点
            volume = s.get("volume_delta", -5)
            # 加入微小的随机延迟偏移，避免“过度完美同步”带来的 AI 感
            offset = random.randint(-50, 50)
            final_audio = final_audio.overlay(sfx + volume, position=max(0, s["start_ms"] + offset))
            
    # 5. 输出
    final_audio.export(output_path, format="mp3", bitrate="192k")
    return output_path

if __name__ == "__main__":
    # Test stub
    pass
