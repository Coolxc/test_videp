#!/usr/bin/env python3
"""
compute_timeline.py - Compute per-element timeline with sketch/colorize frame offsets.

For each scene, calculates:
  - Total scene duration (via estimate or TTS-informed)
  - Per-element: sketchAtFrame, sketchDurationFrames, colorizeAtFrame, colorizeDurationFrames
  - Global scene start frames

Outputs timeline.json with scene-relative frame references.
Also outputs per-element durationMs for animation engine consumption.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRAME_RATE = 60  # Animation engine runs at 60fps
SKETCH_PHASE_WEIGHT = 2
COLOR_PHASE_WEIGHT = 1
COLOR_SKIP_MULTIPLIER = 1.5


def estimate_scene_duration(scene: dict, draw_mode: str = "sketch_first",
                             transition_ms: int = 800) -> float:
    """Estimate scene duration in seconds based on narration text."""
    elements = scene.get("elements", [])
    n = len(elements)
    total_chars = sum(len(e.get("narration", "")) for e in elements)
    narration_s = max(total_chars / 4.0 * 1.2, n * 1.5)  # ~4 chars/sec + 20% margin

    min_anim_s = n * 2.0
    anim_s = max(min_anim_s, narration_s)

    if draw_mode == "sketch_first" and n > 1:
        transition_s = ((n - 1) * 2 + 1.5) * transition_ms / 1000
    else:
        transition_s = (n - 1) * transition_ms / 1000

    blend_s, hold_s = 1.5, 1.5
    total_s = anim_s + transition_s + blend_s + hold_s

    return max(total_s, 6.0)  # Constraint 3: minimum 6 seconds


def compute_element_durations(scene: dict, scene_duration_s: float,
                               transition_ms: int = 800,
                               draw_mode: str = "sketch_first") -> list[dict]:
    """Allocate per-element animation duration by narration character ratio."""
    elements = scene.get("elements", [])
    n = len(elements)
    blend_s, hold_s = 1.5, 1.5

    if draw_mode == "sketch_first" and n > 1:
        total_transition_s = ((n - 1) * 2 + 1.5) * transition_ms / 1000
    else:
        total_transition_s = (n - 1) * transition_ms / 1000

    anim_budget_ms = max(0, (scene_duration_s - blend_s - hold_s - total_transition_s) * 1000)
    total_chars = sum(len(e.get("narration", "")) for e in elements) or n

    result = []
    for elem in elements:
        chars = len(elem.get("narration", "")) or 1
        duration_ms = max(1500, int(anim_budget_ms * chars / total_chars))
        result.append({
            "id": elem["id"],
            "durationMs": duration_ms,
            "narration": elem.get("narration", ""),
        })

    return result


def compute_timeline_entry(scene: dict, scene_start_frame: int,
                            tts_segments: list[dict] = None,
                            draw_mode: str = "sketch_first",
                            transition_ms: int = 800,
                            fps: int = 30) -> dict:
    """
    Compute one scene's timeline entry with per-element four-segment timing.

    Returns:
        {
            "id": str,
            "startFrame": int,        # global frame
            "durationFrames": int,    # scene duration in frames (Remotion fps)
            "elements": [{
                "id": str,
                "sketchAtFrame": int,          # scene-relative
                "sketchDurationFrames": int,
                "colorizeAtFrame": int,         # scene-relative
                "colorizeDurationFrames": int,
                "narration": str,
            }]
        }
    """
    elements = scene.get("elements", [])
    n = len(elements)

    # Determine scene duration
    if scene.get("duration") is not None:
        scene_duration_s = scene["duration"]
    elif tts_segments:
        # Sum of TTS segment durations + overhead
        total_audio_ms = sum(s.get("duration_ms", 0) for s in tts_segments)
        scene_duration_s = total_audio_ms / 1000.0 + 3.0  # + blend+hold
    else:
        scene_duration_s = estimate_scene_duration(scene, draw_mode, transition_ms)

    # Compute per-element durations
    elem_durations = compute_element_durations(scene, scene_duration_s, transition_ms, draw_mode)

    anim_fps = FRAME_RATE  # 60 fps for animation engine
    render_fps = fps  # 30 fps for Remotion

    # Build element timelines
    element_timelines = []
    blend_s, hold_s = 1.5, 1.5
    transition_s = transition_ms / 1000.0

    if draw_mode == "sketch_first" and n > 1:
        # Sketch pass: elements 0..n-1
        # Phase transition: 1.5x
        # Colorize pass: elements 0..n-1

        # Compute frame positions in animation fps (60fps)
        sketch_start = 0
        for i, elem in enumerate(elem_durations):
            total_frames = round(elem["durationMs"] * anim_fps / 1000)
            sketch_frames = round(total_frames * SKETCH_PHASE_WEIGHT / (SKETCH_PHASE_WEIGHT + COLOR_PHASE_WEIGHT))
            color_frames = total_frames - sketch_frames

            # Colorize starts after all sketches + phase transition
            colorize_start = (
                sum(e["durationMs"] for e in elem_durations) *
                SKETCH_PHASE_WEIGHT / (SKETCH_PHASE_WEIGHT + COLOR_PHASE_WEIGHT)
                + 1.5 * transition_ms
            )
            colorize_start_frames = round(colorize_start * anim_fps / 1000)

            element_timelines.append({
                "id": elem["id"],
                "sketchAtFrame": round(sketch_start * anim_fps / 1000) if i == 0
                                 else round((sketch_start + i * transition_s) * anim_fps / 1000),
                "sketchDurationFrames": sketch_frames,
                "colorizeAtFrame": round(colorize_start_frames + sum(
                    e["durationMs"] for e in elem_durations[:i]
                ) * COLOR_PHASE_WEIGHT / (SKETCH_PHASE_WEIGHT + COLOR_PHASE_WEIGHT) * anim_fps / 1000
                    + i * transition_s * anim_fps / 1000),
                "colorizeDurationFrames": color_frames,
                "narration": elem["narration"],
            })
    else:
        # Sequential mode: do each element fully before next
        current_time = 0.0
        for i, elem in enumerate(elem_durations):
            if i > 0:
                current_time += transition_s

            total_frames = round(elem["durationMs"] * anim_fps / 1000)
            sketch_frames = round(total_frames * SKETCH_PHASE_WEIGHT / (SKETCH_PHASE_WEIGHT + COLOR_PHASE_WEIGHT))
            color_frames = total_frames - sketch_frames

            element_timelines.append({
                "id": elem["id"],
                "sketchAtFrame": round(current_time * anim_fps),
                "sketchDurationFrames": sketch_frames,
                "colorizeAtFrame": round(current_time * anim_fps + sketch_frames),
                "colorizeDurationFrames": color_frames,
                "narration": elem["narration"],
            })
            current_time += elem["durationMs"] / 1000.0

    # Scene total duration (in Remotion fps = 30)
    total_duration_frames = round(scene_duration_s * render_fps)

    # Convert animation frame numbers to Remotion frame numbers (60fps → 30fps)
    render_elements = []
    for et in element_timelines:
        render_elements.append({
            "id": et["id"],
            # Convert from anim fps to render fps
            "sketchAtFrame": round(et["sketchAtFrame"] * render_fps / anim_fps),
            "sketchDurationFrames": max(1, round(et["sketchDurationFrames"] * render_fps / anim_fps)),
            "colorizeAtFrame": round(et["colorizeAtFrame"] * render_fps / anim_fps),
            "colorizeDurationFrames": max(1, round(et["colorizeDurationFrames"] * render_fps / anim_fps)),
            "narration": et["narration"],
        })

    return {
        "id": scene["id"],
        "startFrame": scene_start_frame,
        "durationFrames": total_duration_frames,
        "elements": render_elements,
    }


def compute_timeline(storyboard_path: str, output_path: str = None,
                      tts_data: dict = None, draw_mode: str = "sketch_first",
                      transition_ms: int = 800, fps: int = 30) -> dict:
    """Full timeline computation for all scenes."""
    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    meta = storyboard.get("meta", {})
    scenes = storyboard.get("scenes", [])
    topic = meta.get("topic", "untitled")

    render_fps = fps
    scene_entries = []
    current_frame = 0

    for i, scene in enumerate(scenes):
        scene_id = scene.get("id", f"scene{i+1}")
        tts_segments = None
        if tts_data and scene_id in tts_data:
            tts_segments = tts_data[scene_id].get("segments")

        entry = compute_timeline_entry(
            scene, current_frame, tts_segments, draw_mode, transition_ms, render_fps
        )
        scene_entries.append(entry)

        # Also attach durationMs to scene elements for animation engine
        elem_durations = compute_element_durations(scene, entry["durationFrames"] / render_fps,
                                                    transition_ms, draw_mode)
        for ed in elem_durations:
            for scene_elem in scene.get("elements", []):
                if scene_elem["id"] == ed["id"]:
                    scene_elem["durationMs"] = ed["durationMs"]
                    break

        current_frame += entry["durationFrames"]

    timeline = {
        "fps": render_fps,
        "totalFrames": current_frame,
        "frameReference": "scene-relative",
        "drawMode": draw_mode,
        "scenes": scene_entries,
    }

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
        print(f"  Timeline: {output_path} ({current_frame} frames total)")

    return timeline


def finalize_timeline_with_ffprobe(timeline_path: str, anim_dir: str,
                                    output_path: str = None):
    """Refine timeline by reading actual animation durations via ffprobe."""
    with open(timeline_path, "r", encoding="utf-8") as f:
        timeline = json.load(f)

    for scene in timeline.get("scenes", []):
        scene_id = scene["id"]
        anim_path = os.path.join(anim_dir, f"{scene_id}_final.mp4")
        if not os.path.exists(anim_path):
            continue

        # Get actual duration via ffprobe
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", anim_path],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                actual_duration = float(result.stdout.strip())
                # Correct durationFrames to match actual video
                new_frames = round(actual_duration * timeline["fps"])
                if abs(new_frames - scene["durationFrames"]) > 5:
                    print(f"  Corrected '{scene_id}': {scene['durationFrames']} → {new_frames} frames")
                    scene["durationFrames"] = new_frames
        except Exception as e:
            print(f"  [WARN] ffprobe failed for '{scene_id}': {e}")

    # Recalculate totalFrames
    timeline["totalFrames"] = sum(s["durationFrames"] for s in timeline["scenes"])

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
        print(f"  Finalized timeline: {output_path} ({timeline['totalFrames']} frames)")

    return timeline


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Compute video timeline")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--output", "-o", help="Output timeline.json path")
    parser.add_argument("--draw-mode", default="sketch_first", choices=["sketch_first", "sequential"])
    parser.add_argument("--transition-ms", type=int, default=800)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--ffprobe", help="Animation directory for ffprobe finalization")
    args = parser.parse_args()

    topic = "untitled"
    with open(args.storyboard) as f:
        sb = json.load(f)
        topic = sb.get("meta", {}).get("topic", "untitled")

    output = args.output or str(_PROJECT_ROOT / "output" / topic / "timeline.json")

    timeline = compute_timeline(args.storyboard, output, draw_mode=args.draw_mode,
                                 transition_ms=args.transition_ms, fps=args.fps)

    if args.ffprobe:
        finalize_timeline_with_ffprobe(output, args.ffprobe, output)
