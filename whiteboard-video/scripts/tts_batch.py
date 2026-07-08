#!/usr/bin/env python3
"""
批量 TTS 合成脚本
自动拆分长文本为多个片段，分别合成后拼接为一个 WAV 文件
"""

import argparse
import base64
import os
import struct
import sys
import wave
import tempfile
import shutil

from dotenv import load_dotenv

from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.tts.v20190823 import tts_client, models

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))


def normalize_punctuation(text: str) -> str:
    """中文标点转英文标点"""
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


def split_text(text: str, max_chars: int = 150) -> list:
    """
    将文本拆分为多个片段，每段不超过 max_chars 字符
    优先在句号、逗号等标点处断开
    """
    if len(text) <= max_chars:
        return [text]

    segments = []
    current = ""
    
    # 按句子分割（保留分隔符）
    sentences = []
    i = 0
    while i < len(text):
        # 找下一个句末标点
        end = len(text)
        for sep in ['.', ',', '?', '!', ';', ':', '，', '。', '？', '！', '；', '：']:
            pos = text.find(sep, i)
            if pos != -1 and pos < end:
                end = pos + 1
        
        if end == len(text):
            sentences.append(text[i:])
            break
        else:
            sentences.append(text[i:end])
            i = end
    
    # 组装成不超过 max_chars 的段落
    for sent in sentences:
        if not sent.strip():
            continue
        if len(current) + len(sent) <= max_chars:
            current += sent
        else:
            if current:
                segments.append(current)
            # 如果单句话就超长，强制截断（尽量在空格处断）
            if len(sent) > max_chars:
                segments.append(sent[:max_chars])
                current = sent[max_chars:]
            else:
                current = sent
    
    if current:
        segments.append(current)
    
    return segments


def synthesize_single(text: str, output_path: str, voice_type: int = 602005, speed: float = 1.1) -> float:
    """调用腾讯云 TTS 合成单段语音"""
    secret_id = os.getenv("TENCENT_SECRET_ID")
    secret_key = os.getenv("TENCENT_SECRET_KEY")

    cred = credential.Credential(secret_id, secret_key)

    http_profile = HttpProfile()
    http_profile.endpoint = "tts.tencentcloudapi.com"

    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile

    client = tts_client.TtsClient(cred, "ap-guangzhou", client_profile)

    req = models.TextToVoiceRequest()
    req.Text = normalize_punctuation(text)
    req.SessionId = f"session-{hash(text) & 0xFFFFFFFF}"
    req.VoiceType = voice_type
    req.Speed = speed
    req.SampleRate = 16000
    req.Codec = "wav"

    resp = client.TextToVoice(req)
    audio_data = base64.b64decode(resp.Audio)

    with open(output_path, 'wb') as f:
        f.write(audio_data)

    with wave.open(output_path, 'rb') as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        duration = frames / float(rate)

    return duration


def concatenate_wav_files(wav_files: list, output_path: str) -> float:
    """将多个 WAV 文件拼接成一个"""
    if not wav_files:
        return 0.0
    
    data = []
    sample_rate = None
    n_channels = None
    sample_width = None
    
    for wav_file in wav_files:
        with wave.open(wav_file, 'rb') as wf:
            if sample_rate is None:
                sample_rate = wf.getframerate()
                n_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
            
            frames = wf.readframes(wf.getnframes())
            data.append(frames)
    
    with wave.open(output_path, 'wb') as wf:
        wf.setnchannels(n_channels or 1)
        wf.setsampwidth(sample_width or 2)
        wf.setframerate(sample_rate or 16000)
        wf.setnframes(sum(len(d) for d in data) // (sample_width or 2))
        
        for d in data:
            wf.writeframes(d)
    
    total_duration = sum(len(d) for d in data) / (sample_rate * (sample_width or 2))
    return total_duration


def main():
    parser = argparse.ArgumentParser(description="批量 TTS 合成")
    parser.add_argument("--text", type=str, help="要合成的文本")
    parser.add_argument("--text-file", type=str, help="文本文件路径")
    parser.add_argument("--output", "-o", type=str, required=True, help="输出 WAV 文件路径")
    parser.add_argument("--voice-type", type=int, default=int(os.getenv("TENCENT_TTS_VOICE_TYPE", "602005")))
    parser.add_argument("--speed", type=float, default=float(os.getenv("TENCENT_TTS_SPEED", "1.1")))
    parser.add_argument("--max-chars", type=int, default=150, help="每段最大字符数")

    args = parser.parse_args()

    if args.text_file:
        with open(args.text_file, 'r', encoding='utf-8') as f:
            text = f.read().strip()
    elif args.text:
        text = args.text
    else:
        print("ERROR: provide --text or --text-file")
        sys.exit(1)

    print(f"原始文本长度: {len(text)} 字符")
    
    # 拆分文本
    segments = split_text(text, args.max_chars)
    print(f"拆分为 {len(segments)} 个片段:")
    for i, seg in enumerate(segments):
        print(f"  [{i+1}] ({len(seg)}字) {seg[:40]}...")

    # 临时目录存放各段音频
    temp_dir = tempfile.mkdtemp(prefix='tts_')
    wav_files = []
    total_duration = 0.0

    try:
        for i, seg in enumerate(segments):
            temp_wav = os.path.join(temp_dir, f'segment_{i}.wav')
            print(f"\n[{i+1}/{len(segments)}] 合成中...")
            duration = synthesize_single(seg, temp_wav, args.voice_type, args.speed)
            wav_files.append(temp_wav)
            total_duration += duration
            print(f"  时长: {duration:.1f}s")

        # 确保输出目录存在
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

        # 拼接所有音频
        print(f"\n拼接 {len(wav_files)} 个音频文件...")
        final_duration = concatenate_wav_files(wav_files, args.output)
        print(f"\n✅ 输出: {args.output}")
        print(f"   总时长: {final_duration:.1f}s")
        print(f"   片段数: {len(segments)}")

    finally:
        # 清理临时文件
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    main()
