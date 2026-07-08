#!/usr/bin/env python3
"""
cosy_client.py
CosyVoice / GPT-SoVITS 本地 API 客户端
支持实时语音合成并保存为音频文件。
"""

import os
import requests
import json
from pathlib import Path
from dotenv import load_dotenv

# 加载配置
workflow_root = Path("/Users/max/code/whiteboard-animation-skill/whiteboard-video-workflow")
load_dotenv(workflow_root / ".env")

API_URL = os.getenv("COSYVOICE_API_URL", "http://192.168.233.50:9880/tts")
VOICE_ID = os.getenv("COSYVOICE_VOICE_ID", "e000fba358b1")

def synthesize_voice(text, output_path, speed=1.1):
    """
    通过局域网 API 合成语音。
    支持 GPT-SoVITS / CosyVoice 常见的 API 格式。
    """
    print(f"  Synthesizing voice: '{text[:20]}...' [ID: {VOICE_ID}]")
    
    # 构造请求 (按 GPT-SoVITS 标准 API v2 格式)
    # 如果是 CosyVoice 官方 API，payload 结构可能略有不同，
    # 我们这里先采用最通用的适配逻辑。
    payload = {
        "text": text,
        "text_lang": "zh",
        "spk_id": VOICE_ID, # 或者用 spk_id
        "speed_factor": speed,
        "streaming_mode": False
    }
    
    # 针对某些 API 可能需要不同的参数名，我们可以做兼容
    # 例如：FunAudioLLM 的 CosyVoice 常用 "voice" 或 "spk_id"
    payload_alt = {
        "text": text,
        "voice": VOICE_ID,
        "speed": speed
    }

    try:
        # 先尝试标准 /tts 路径
        response = requests.post(API_URL, json=payload, timeout=30)
        
        # 如果 404 或 405，尝试根路径或其他常见路径
        if response.status_code in [404, 405]:
            alt_url = API_URL.replace("/tts", "")
            response = requests.post(alt_url, json=payload_alt, timeout=30)
            
        response.raise_for_status()
        
        # 写入文件 (API 应该返回的是音频二进制流)
        with open(output_path, "wb") as f:
            f.write(response.content)
            
        print(f"  SUCCESS: Voice saved to {output_path}")
        return True
        
    except Exception as e:
        print(f"  Synthesis error: {e}")
        return False

if __name__ == "__main__":
    # Test stub
    test_path = "test_voice.wav"
    synthesize_voice("你好，这是全自动配音系统测试。准备开始量产。", test_path)
