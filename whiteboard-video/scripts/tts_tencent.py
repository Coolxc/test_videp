#!/usr/bin/env python3
"""
腾讯云 TTS 脚本
使用专业梓欣 602005 音色，1.1倍速
输出 WAV 文件

用法:
  python3 tts_tencent.py --text "你好世界" --output output.wav
  python3 tts_tencent.py --text-file script.txt --output output.wav
"""

import argparse
import base64
import os
import struct
import sys
import wave

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.tts.v20190823 import tts_client, models


def normalize_punctuation(text: str) -> str:
    """中文标点转英文标点（部分 TTS 引擎对中文标点发音不稳定）"""
    mapping = {
        '，': ',',
        '。': '.',
        '？': '?',
        '！': '!',
        '；': ';',
        '：': ':',
        '"': '"',
        '"': '"',
        ''': "'",
        ''': "'",
        '（': '(',
        '）': ')',
    }
    for zh, en in mapping.items():
        text = text.replace(zh, en)
    return text


def synthesize(text: str, output_path: str, voice_type: int = 602005, speed: float = 1.1):
    """调用腾讯云 TTS 合成语音"""
    secret_id = os.getenv("TENCENT_SECRET_ID")
    secret_key = os.getenv("TENCENT_SECRET_KEY")

    if not secret_id or not secret_key:
        print("ERROR: TENCENT_SECRET_ID / TENCENT_SECRET_KEY not found in .env")
        sys.exit(1)

    cred = credential.Credential(secret_id, secret_key)

    http_profile = HttpProfile()
    http_profile.endpoint = "tts.tencentcloudapi.com"

    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile

    client = tts_client.TtsClient(cred, "ap-guangzhou", client_profile)

    # 标点规范化
    text = normalize_punctuation(text)

    req = models.TextToVoiceRequest()
    req.Text = text
    req.SessionId = f"session-{hash(text) & 0xFFFFFFFF}"
    req.VoiceType = voice_type
    req.Speed = speed
    req.SampleRate = 16000
    req.Codec = "wav"

    print(f"Synthesizing: {text[:50]}...")
    print(f"  Voice: {voice_type} (专业梓欣)")
    print(f"  Speed: {speed}x")

    resp = client.TextToVoice(req)

    # Decode audio
    audio_data = base64.b64decode(resp.Audio)

    # Write WAV file
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(audio_data)

    # Get duration from WAV
    try:
        with wave.open(output_path, 'rb') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            duration = frames / float(rate)
    except Exception:
        duration = 0

    print(f"  Output: {output_path}")
    print(f"  Duration: {duration:.1f}s")

    return duration


def main():
    parser = argparse.ArgumentParser(description="腾讯云 TTS (专业梓欣 602005)")
    parser.add_argument("--text", type=str, help="要合成的文本")
    parser.add_argument("--text-file", type=str, help="文本文件路径")
    parser.add_argument("--output", "-o", type=str, required=True, help="输出 WAV 文件路径")
    parser.add_argument("--voice-type", type=int, default=int(os.getenv("TENCENT_TTS_VOICE_TYPE", "602005")))
    parser.add_argument("--speed", type=float, default=float(os.getenv("TENCENT_TTS_SPEED", "1.1")))

    args = parser.parse_args()

    if args.text_file:
        with open(args.text_file, 'r', encoding='utf-8') as f:
            text = f.read().strip()
    elif args.text:
        text = args.text
    else:
        print("ERROR: provide --text or --text-file")
        sys.exit(1)

    duration = synthesize(text, args.output, args.voice_type, args.speed)
    print(f"\n=== Done: {duration:.1f}s ===")


if __name__ == "__main__":
    main()
