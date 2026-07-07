#!/usr/bin/env python3
"""
generate_subtitles.py - Generate SRT subtitle file aligned to sketch phase timing.

Each element's narration text is displayed during its sketch phase.
SRT timestamps align with the Remotion output (30fps).
"""

import json
import os
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def generate_srt(timeline: dict, storyboard: dict, output_path: str = None) -> str:
    """
    Generate SRT subtitle content from timeline + storyboard.

    Each element's narration is shown during its sketchAtFrame → sketchAtFrame + sketchDurationFrames.
    Uses scene-level startFrame offset to compute global timestamps.
    """
    fps = timeline.get("fps", 30)
    scenes = timeline.get("scenes", [])

    srt_entries = []
    subtitle_index = 1

    for tscene in scenes:
        scene_start_frame = tscene.get("startFrame", 0)
        elements = tscene.get("elements", [])

        for elem in elements:
            text = elem.get("narration", "")
            if not text:
                continue

            start_frame = scene_start_frame + elem.get("sketchAtFrame", 0)
            duration_frames = elem.get("sketchDurationFrames", 30)
            end_frame = start_frame + duration_frames

            start_time = _frames_to_srt_time(start_frame, fps)
            end_time = _frames_to_srt_time(end_frame, fps)

            srt_entries.append(f"{subtitle_index}")
            srt_entries.append(f"{start_time} --> {end_time}")
            srt_entries.append(text)
            srt_entries.append("")
            subtitle_index += 1

    # Also add scene-level voiceText fallback for scenes without per-element narration
    storyboard_scenes = {s["id"]: s for s in storyboard.get("scenes", [])}
    for tscene in scenes:
        sid = tscene["id"]
        sb_scene = storyboard_scenes.get(sid, {})
        elements = tscene.get("elements", [])

        # Check if any element has narration
        has_narration = any(e.get("narration", "") for e in elements)
        if not has_narration and sb_scene.get("voiceText"):
            scene_start = tscene.get("startFrame", 0)
            scene_dur = tscene.get("durationFrames", 0)
            start_time = _frames_to_srt_time(scene_start, fps)
            end_time = _frames_to_srt_time(scene_start + scene_dur, fps)
            srt_entries.append(f"{subtitle_index}")
            srt_entries.append(f"{start_time} --> {end_time}")
            srt_entries.append(sb_scene["voiceText"])
            srt_entries.append("")
            subtitle_index += 1

    srt_content = "\n".join(srt_entries)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        print(f"  Subtitles: {output_path} ({subtitle_index - 1} entries)")

    return srt_content


def _frames_to_srt_time(frame: int, fps: float) -> str:
    """Convert frame number to SRT time format (HH:MM:SS,mmm)."""
    total_seconds = frame / fps
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    milliseconds = int((total_seconds - int(total_seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate SRT subtitles")
    parser.add_argument("--timeline", "-t", required=True, help="Path to timeline.json")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--output", "-o", help="Output subtitle.srt path")
    args = parser.parse_args()

    with open(args.timeline, "r", encoding="utf-8") as f:
        timeline = json.load(f)
    with open(args.storyboard, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    topic = storyboard.get("meta", {}).get("topic", "untitled")
    output = args.output or str(_PROJECT_ROOT / "output" / topic / "subtitles.srt")

    generate_srt(timeline, storyboard, output)
