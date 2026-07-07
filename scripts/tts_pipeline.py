#!/usr/bin/env python3
"""
tts_pipeline.py - Full TTS pipeline with silence detection and segmentation.

Synthesizes whole voiceText per scene, then detects silence to segment
per-element narration timing. Supports Tencent Cloud TTS and falls back
to edge-tts (free, offline-compatible).
"""

import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

from pydub import AudioSegment
from pydub.silence import detect_silence
import numpy as np


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TTS_CACHE_DIR = _PROJECT_ROOT / "cache" / "tts"


def normalize_punctuation(text: str) -> str:
    """Convert Chinese punctuation to English for more stable TTS."""
    mapping = {
        "，": ",", "。": ".", "？": "?", "！": "!",
        "；": ";", "：": ":", "“": "\"", "”": "\"",
        "‘": "'", "’": "'", "（": "(", "）": ")",
    }
    for zh, en in mapping.items():
        text = text.replace(zh, en)
    return text


def get_cache_path(text: str, voice: int = 602005, speed: float = 1.1) -> Path:
    """Get cache path for a given TTS request."""
    key = hashlib.sha256(f"{text}_{voice}_{speed}".encode()).hexdigest()[:16]
    return _TTS_CACHE_DIR / f"{key}.wav"


def synthesize_tencent(text: str, output_path: str, voice: int = 602005, speed: float = 1.1) -> float:
    """Synthesize via Tencent Cloud TTS (subprocess)."""
    tts_script = _PROJECT_ROOT / "whiteboard-video" / "scripts" / "tts_tencent.py"
    if not tts_script.exists():
        raise FileNotFoundError(f"TTS script not found: {tts_script}")

    # Pass credentials via environment
    env = os.environ.copy()
    if os.environ.get("TENCENT_SECRET_ID"):
        env["TENCENT_SECRET_ID"] = os.environ["TENCENT_SECRET_ID"]
    if os.environ.get("TENCENT_SECRET_KEY"):
        env["TENCENT_SECRET_KEY"] = os.environ["TENCENT_SECRET_KEY"]

    text = normalize_punctuation(text)

    # Check text length limit (150 chars for Tencent)
    if len(text) > 150:
        print(f"  [WARN] Text exceeds 150 chars ({len(text)}), splitting...")
        return _synthesize_long_text(text, output_path, voice, speed)

    result = subprocess.run(
        [sys.executable, str(tts_script),
         "--text", text,
         "--output", output_path,
         "--voice-type", str(voice),
         "--speed", str(speed)],
        capture_output=True, text=True, env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"TTS failed: {result.stderr}")

    print(f"  TTS: {result.stdout.strip()}")

    # Parse duration from output
    for line in result.stdout.split("\n"):
        if "Duration" in line:
            try:
                return float(line.split()[-1].replace("s", ""))
            except (ValueError, IndexError):
                pass
    return 0.0


def _synthesize_long_text(text: str, output_path: str, voice: int = 602005, speed: float = 1.1) -> float:
    """Split long text and concatenate audio segments."""
    # Split by sentence
    import re
    sentences = re.split(r"([。！？.!?])", text)
    chunks = []
    current = ""
    for s in sentences:
        if len(current) + len(s) <= 140:
            current += s
        else:
            if current:
                chunks.append(current)
            current = s
    if current:
        chunks.append(current)

    print(f"  Split into {len(chunks)} chunks")

    combined = AudioSegment.silent(duration=0)
    total_duration = 0.0

    for i, chunk in enumerate(chunks):
        chunk_path = output_path.replace(".wav", f"_part{i}.wav")
        result = subprocess.run(
            [sys.executable, str(_PROJECT_ROOT / "whiteboard-video" / "scripts" / "tts_tencent.py"),
             "--text", chunk.strip(),
             "--output", chunk_path],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and os.path.exists(chunk_path):
            seg = AudioSegment.from_wav(chunk_path)
            combined += seg
            total_duration += len(seg) / 1000.0
            os.remove(chunk_path)

    combined.export(output_path, format="wav")
    return total_duration


def synthesize_edge_tts(text: str, output_path: str, voice: str = "zh-CN-XiaoxiaoNeural",
                         speed: float = 1.1) -> float:
    """Fallback TTS using edge-tts (free, local)."""
    import edge_tts

    text = normalize_punctuation(text)

    async def _do():
        communicate = edge_tts.Communicate(text, voice, rate=f"+{int((speed - 1.0) * 100)}%")
        await communicate.save(output_path)

    import asyncio
    asyncio.run(_do())

    audio = AudioSegment.from_file(output_path)
    duration = len(audio) / 1000.0
    print(f"  Edge-TTS: {duration:.1f}s -> {output_path}")
    return duration


def detect_silence_segments(audio_path: str, min_silence_ms: int = 300,
                             silence_thresh: int = -40) -> list[dict]:
    """Detect non-silent segments in audio and return speech intervals."""
    audio = AudioSegment.from_wav(audio_path)

    # Find silent parts
    silent_ranges = detect_silence(
        audio,
        min_silence_len=min_silence_ms,
        silence_thresh=silence_thresh,
    )

    total_duration = len(audio)
    speech_segments = []

    if not silent_ranges:
        # No silence found → whole file is one segment
        speech_segments.append({"start_ms": 0, "end_ms": total_duration})
        return speech_segments

    # Invert: find speech segments between silences
    prev_end = 0
    for start, end in silent_ranges:
        if start > prev_end:
            speech_segments.append({"start_ms": prev_end, "end_ms": start})
        prev_end = end

    # Last segment
    if prev_end < total_duration:
        speech_segments.append({"start_ms": prev_end, "end_ms": total_duration})

    return speech_segments


def align_narration_to_scenes(audio_path: str, storyboard: dict,
                               scene_index: int) -> list[dict]:
    """
    Align detected speech segments to per-element narration.

    Returns list of {element_id, start_ms, end_ms, duration_ms}.
    """
    scene = storyboard["scenes"][scene_index]
    elements = scene.get("elements", [])
    if not elements:
        return []

    segments = detect_silence_segments(audio_path)
    if not segments:
        # Fallback: split evenly by character count
        return _fallback_split(audio_path, elements)

    # Try to align by character ratio if segment count doesn't match
    if len(segments) != len(elements):
        print(f"  [WARN] Detected {len(segments)} speech segments for "
              f"{len(elements)} elements, using character-ratio split")
        return _fallback_split(audio_path, elements)

    result = []
    for i, (elem, seg) in enumerate(zip(elements, segments)):
        result.append({
            "element_id": elem["id"],
            "start_ms": seg["start_ms"],
            "end_ms": seg["end_ms"],
            "duration_ms": seg["end_ms"] - seg["start_ms"],
        })

    return result


def _fallback_split(audio_path: str, elements: list[dict]) -> list[dict]:
    """Split audio duration proportionally by narration character count."""
    audio = AudioSegment.from_wav(audio_path)
    total_duration = len(audio)
    total_chars = sum(len(e.get("narration", "")) for e in elements) or len(elements)

    result = []
    current_ms = 0
    for elem in elements:
        char_ratio = len(elem.get("narration", "")) / max(1, total_chars)
        elem_duration = int(total_duration * char_ratio)
        result.append({
            "element_id": elem["id"],
            "start_ms": current_ms,
            "end_ms": current_ms + elem_duration,
            "duration_ms": elem_duration,
        })
        current_ms += elem_duration

    # Adjust last element to consume remainder
    if result:
        result[-1]["end_ms"] = total_duration
        result[-1]["duration_ms"] = total_duration - (result[-1]["start_ms"] if len(result) > 1 else 0)

    return result


def tts_pipeline(storyboard_path: str, output_dir: str = None,
                  provider: str = "tencent", voice: int = 602005,
                  speed: float = 1.1) -> dict:
    """
    Full TTS pipeline: synthesize per-scene → detect silence → align narration.

    Returns dict of scene_id -> {"audio_path", "segments"}.
    """
    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    meta = storyboard.get("meta", {})
    scenes = storyboard.get("scenes", [])

    if output_dir is None:
        topic = meta.get("topic", "untitled")
        output_dir = str(_PROJECT_ROOT / "output" / topic)

    audio_dir = os.path.join(output_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(_TTS_CACHE_DIR, exist_ok=True)

    results = {}

    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        voice_text = scene.get("voiceText", "")
        if not voice_text:
            print(f"  [SKIP] Scene '{scene_id}': no voiceText")
            continue

        print(f"\n[{i+1}/{len(scenes)}] TTS: {scene_id}")

        output_path = os.path.join(audio_dir, f"{scene_id}.wav")

        # Check cache
        cache_path = get_cache_path(voice_text, voice, speed)
        if cache_path.exists():
            print(f"  Cache hit: {cache_path}")
            import shutil
            shutil.copy(cache_path, output_path)
            duration = len(AudioSegment.from_wav(output_path)) / 1000.0
        else:
            # Synthesize
            if provider == "tencent":
                duration = synthesize_tencent(voice_text, output_path, voice, speed)
            else:
                duration = synthesize_edge_tts(voice_text, output_path, speed)

            # Save to cache
            if os.path.exists(output_path):
                import shutil
                os.makedirs(_TTS_CACHE_DIR, exist_ok=True)
                shutil.copy(output_path, cache_path)

        # Align narration segments
        segments = align_narration_to_scenes(output_path, storyboard, i)
        print(f"  Duration: {duration:.1f}s, segments: {len(segments)}")

        results[scene_id] = {
            "audio_path": output_path,
            "duration_s": duration,
            "segments": segments,
        }

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TTS pipeline for storyboard")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--output-dir", "-o", help="Output directory")
    parser.add_argument("--provider", default="tencent", choices=["tencent", "edge-tts"])
    parser.add_argument("--voice", type=int, default=602005)
    parser.add_argument("--speed", type=float, default=1.1)
    args = parser.parse_args()

    result = tts_pipeline(args.storyboard, args.output_dir, args.provider, args.voice, args.speed)
    print(f"\nTTS complete for {len(result)} scenes")
