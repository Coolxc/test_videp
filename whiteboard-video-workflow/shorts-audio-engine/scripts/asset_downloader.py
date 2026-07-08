#!/usr/bin/env python3
"""
asset_downloader.py
Shorts Audio Engine - 安全音效抓取器
强制执行 CC0 (Public Domain) 过滤，确保版权 100% 安全。
"""

import os
import requests
import json
from pathlib import Path
from dotenv import load_dotenv

# 加载配置
workflow_root = Path("/Users/max/code/whiteboard-animation-skill/whiteboard-video-workflow")
load_dotenv(workflow_root / ".env")

API_KEY = os.getenv("FREESOUND_API_KEY")
BASE_URL = "https://freesound.org/apiv2"

def download_cc0_sfx(keyword, save_dir, filename=None):
    """
    搜索并下载 CC0 协议的音效。
    """
    if not API_KEY:
        print("Error: FREESOUND_API_KEY not found in .env")
        return None

    save_path = Path(save_dir)
    save_path.mkdir(parents=True, exist_ok=True)
    
    target_filename = filename if filename else f"{keyword}.wav"
    final_path = save_path / target_filename
    
    if final_path.exists():
        print(f"  Asset already exists: {target_filename}")
        return str(final_path)

    print(f"  Searching Freesound for CC0: {keyword}...")
    
    # 1. 文本搜索 (强制加 license:"Creative Commons 0" 过滤器)
    search_url = f"{BASE_URL}/search/text/"
    params = {
        "query": keyword,
        "filter": 'license:"Creative Commons 0"',
        "sort": "rating_desc",
        "fields": "id,name,previews",
        "page_size": 1,
        "token": API_KEY
    }
    
    try:
        response = requests.get(search_url, params=params)
        response.raise_for_status()
        results = response.json().get("results", [])
        
        if not results:
            print(f"  No CC0 results found for: {keyword}")
            return None
        
        # 2. 获取最匹配的预览链接 (通常预览是足够高质量的 mp3/ogg)
        best_match = results[0]
        preview_url = best_match.get("previews", {}).get("preview-hq-mp3")
        
        if not preview_url:
            print(f"  No preview URL for: {keyword}")
            return None
            
        # 3. 下载
        print(f"  Downloading: {best_match.get('name')} -> {target_filename}")
        audio_data = requests.get(preview_url)
        audio_data.raise_for_status()
        
        with open(final_path, "wb") as f:
            f.write(audio_data.content)
            
        print(f"  SUCCESS: {final_path}")
        return str(final_path)
        
    except Exception as e:
        print(f"  Download error: {e}")
        return None

def main():
    import sys
    # 模拟“热身”下载
    assets_dir = "/Users/max/code/whiteboard-animation-skill/shorts-audio-engine/assets/audio"
    warmup_items = [
        ("pencil scratch", "pencil_scratch.wav"),
        ("door knock", "knock.wav"),
        ("tension drone", "tension_drone.wav"),
        ("room ambience", "room_ambience.wav")
    ]
    
    print("🚀 Starting SFX Warmup (Strict CC0 Mode)...")
    for keyword, fname in warmup_items:
        download_cc0_sfx(keyword, assets_dir, fname)

if __name__ == "__main__":
    main()
