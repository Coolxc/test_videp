#!/usr/bin/env python3
"""
audio_mixer.py - Three-layer audio mixer.

Layers:
  1. Voice (TTS output, ~+5dB boost for Tencent)
  2. Ambient background sound (looping, -25dB)
  3. SFX (defined in timeline, -5dB)

Uses pydub for audio processing.
Outputs a single mixed audio file per scene.
"""

import json
import os
import sys
from pathlib import Path

from pydub import AudioSegment


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def mix_scene_audio(voice_path: str, scene_duration_ms: int,
                     ambient_path: str = None,
                     output_path: str = None) -> str:
    """
    Mix audio for a single scene.

    Args:
        voice_path: Path to TTS voice WAV file.
        scene_duration_ms: Total scene duration in milliseconds.
        ambient_path: Path to ambient background audio (looped).
        output_path: Output path for mixed audio.

    Returns:
        Path to output mixed audio file.
    """
    if output_path is None:
        output_path = voice_path.replace(".wav", "_mixed.wav")

    # 1. Create silent canvas
    final_audio = AudioSegment.silent(duration=scene_duration_ms)

    # 2. Mix ambient (background, -25dB, looped)
    if ambient_path and os.path.exists(ambient_path):
        ambient = AudioSegment.from_file(ambient_path)
        loops = (scene_duration_ms // len(ambient)) + 1
        ambient_loop = (ambient * loops)[:scene_duration_ms]
        final_audio = final_audio.overlay(ambient_loop - 25)

    # 3. Mix voice (+5dB boost for Tencent TTS)
    if os.path.exists(voice_path):
        voice = AudioSegment.from_wav(voice_path)
        voice_boosted = voice + 5  # +5dB
        final_audio = final_audio.overlay(voice_boosted, position=0)

    # 4. Export
    final_audio.export(output_path, format="wav")
    print(f"  Mixed audio: {output_path}")
    return output_path


def mix_all_scenes(storyboard_path: str, audio_dir: str,
                    ambient_path: str = None,
                    timeline_path: str = None,
                    output_dir: str = None) -> dict:
    """Mix audio for all scenes."""
    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    meta = storyboard.get("meta", {})
    scenes = storyboard.get("scenes", [])
    topic = meta.get("topic", "untitled")

    # Load timeline for durations
    timeline = None
    if timeline_path and os.path.exists(timeline_path):
        with open(timeline_path, "r", encoding="utf-8") as f:
            timeline = json.load(f)

    if output_dir is None:
        output_dir = str(_PROJECT_ROOT / "output" / topic)
    mixed_dir = os.path.join(output_dir, "audio")
    os.makedirs(mixed_dir, exist_ok=True)

    results = {}

    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        voice_path = os.path.join(audio_dir, f"{scene_id}.wav")

        if not os.path.exists(voice_path):
            print(f"  [SKIP] '{scene_id}': no voice file")
            continue

        # Get scene duration
        scene_duration_ms = 10000  # default fallback
        if timeline:
            for tscene in timeline.get("scenes", []):
                if tscene["id"] == scene_id:
                    fps = timeline.get("fps", 30)
                    scene_duration_ms = int(tscene["durationFrames"] / fps * 1000)
                    break

        output_path = os.path.join(mixed_dir, f"{scene_id}_mixed.wav")
        mix_scene_audio(voice_path, scene_duration_ms, ambient_path, output_path)
        results[scene_id] = output_path

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Three-layer audio mixer")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--audio-dir", "-a", help="Directory containing scene WAV files")
    parser.add_argument("--ambient", help="Path to ambient background audio")
    parser.add_argument("--timeline", "-t", help="Path to timeline.json for durations")
    parser.add_argument("--output-dir", "-o", help="Output directory")
    args = parser.parse_args()

    with open(args.storyboard, "r", encoding="utf-8") as f:
        sb = json.load(f)
    topic = sb.get("meta", {}).get("topic", "untitled")

    audio_dir = args.audio_dir or str(_PROJECT_ROOT / "output" / topic / "audio")

    mix_all_scenes(args.storyboard, audio_dir, args.ambient, args.timeline, args.output_dir)
