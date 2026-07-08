#!/usr/bin/env python3
"""
pipeline.py
Shorts Audio Engine - Orchestrator
将 SRT/字幕流转换为最终混音音轨。支持实时采样与自动补全。
"""

import argparse
import json
import sys
from pathlib import Path

# Add scripts dir to path for imports
sys.path.append(str(Path(__file__).parent))

from mixer import mix_audio_layers
from sfx_library import get_sfx_for_text, get_ambient_path, SFX_MAP
from asset_downloader import download_cc0_sfx
from cosy_client import synthesize_voice

def run_audio_pipeline(data_path, assets_dir, output_path, voice_dir=None, auto_fetch=False):
    """
    data_path: Path to storyboard.json or srt_data.json
    assets_dir: Path to SFX/Ambient library
    voice_dir: Directory where pre-generated voice files are stored
    auto_fetch: Whether to download missing SFX from Freesound
    """
    # 建立临时配音文件夹
    temp_voice_path = Path(data_path).parent / "temp_voices"
    temp_voice_path.mkdir(exist_ok=True)
    
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 兼容 Storyboard 和 SRT 格式
    scenes = data.get("scenes", [])
    if not scenes and "segments" in data: 
        scenes = [{"segments": data["segments"]}]
    
    total_duration_ms = data.get("totalDuration", 0)
    if total_duration_ms == 0:
        total_duration_ms = 60000 # Default 1 min
        
    voice_segments = []
    sfx_list = []
    mood = data.get("mood", "default")
    
    # --- 1. 处理每一段语音和触发音效 ---
    for i, scene in enumerate(scenes):
        scene_start = scene.get("startTime", 0)
        scene_segments = scene.get("segments", [])
        
        for j, seg in enumerate(scene_segments):
            text = seg.get("text", "")
            start_ms = scene_start + seg.get("relativeStart", 0)
            
            # A. 语音映射 (优先查找 voice_dir，如果没有，则实时合成)
            voice_filename = f"voice_{len(voice_segments)}.mp3"
            voice_path = Path(voice_dir) / voice_filename if voice_dir else None
            target_voice_path = temp_voice_path / voice_filename
            
            # 策略：如果指定的 voice_dir 里没有，就检查缓存，缓存没有就合成
            final_voice_file = None
            if voice_path and voice_path.exists():
                final_voice_file = str(voice_path)
            elif target_voice_path.exists():
                final_voice_file = str(target_voice_path)
            else:
                print(f"  Synthesizing voice for: {text[:15]}...")
                success = synthesize_voice(text, str(target_voice_path))
                if success:
                    final_voice_file = str(target_voice_path)
            
            if final_voice_file:
                voice_segments.append({
                    "path": final_voice_file,
                    "start_ms": start_ms,
                    "volume_delta": 0
                })
            
            # B. SFX 关键词匹配
            matched_sfx = get_sfx_for_text(text, assets_dir)
            
            # --- V2 自动补全功能 ---
            if auto_fetch:
                for kw, fname in SFX_MAP.items():
                    if kw in text:
                        local_path = Path(assets_dir) / fname
                        if not local_path.exists():
                            print(f"  Auto-fetching missing SFX: '{kw}'...")
                            download_cc0_sfx(kw, assets_dir, fname)
                            matched_sfx = get_sfx_for_text(text, assets_dir)

            for s_path in matched_sfx:
                sfx_list.append({
                    "path": s_path,
                    "start_ms": start_ms,
                    "volume_delta": -5
                })
                
    # --- 2. 获取背景音 ---
    ambient_path = get_ambient_path(mood, assets_dir)
    
    # --- 3. 最终混音 ---
    print(f"Mixing {len(voice_segments)} voices and {len(sfx_list)} SFX...")
    result = mix_audio_layers(
        voice_segments=voice_segments,
        total_duration_ms=total_duration_ms,
        ambient_path=ambient_path,
        sfx_list=sfx_list,
        output_path=output_path
    )
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Path to storyboard.json")
    parser.add_argument("--assets", required=True, help="Path to audio assets (sfx/ambient)")
    parser.add_argument("--voice-dir", help="Dir containing voice_N.mp3 files")
    parser.add_argument("--output", default="final_mix.mp3")
    parser.add_argument("--auto-fetch", action="store_true", help="Download missing SFX from Freesound")
    
    args = parser.parse_args()
    
    try:
        mix_file = run_audio_pipeline(
            args.data, args.assets, args.output, 
            voice_dir=args.voice_dir, 
            auto_fetch=args.auto_fetch
        )
        print(f"COMPLETE: {mix_file}")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
