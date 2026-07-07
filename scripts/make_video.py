#!/usr/bin/env python3
"""
make_video.py - Main entry point for the whiteboard video pipeline.

Orchestrates all steps from storyboard → final video with checkpoint-based
resumability. Supports two modes:
  - video_first: Generate silent video + subtitles (no TTS required)
  - full: Full pipeline including TTS + audio mixing

Usage:
  # Step 1: Generate prompts (user then creates images)
  python scripts/make_video.py --storyboard storyboard.json --mode video-first

  # Step 2: Generate video (after images are in place)
  python scripts/make_video.py --storyboard storyboard.json --mode video-first --skip-prompts

  # Full mode (requires TTS API key)
  python scripts/make_video.py --storyboard storyboard.json --mode full
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"


def _import_step(name):
    """Dynamic import of a step module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(_SCRIPTS_DIR / f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get_output_dir(storyboard: dict) -> Path:
    topic = storyboard.get("meta", {}).get("topic", "untitled")
    return _PROJECT_ROOT / "output" / f"{topic}-{time.strftime('%Y%m%d')}"


def _load_storyboard(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_checkpoint(output_dir: Path) -> dict:
    cp_path = output_dir / ".checkpoint.json"
    if cp_path.exists():
        with open(cp_path, "r") as f:
            return json.load(f)
    return {}


def _write_checkpoint(output_dir: Path, step: str, data: dict = None):
    cp_path = output_dir / ".checkpoint.json"
    cp = _read_checkpoint(output_dir)
    cp[step] = {"done": True, "timestamp": time.time(), "data": data or {}}
    os.makedirs(output_dir, exist_ok=True)
    with open(cp_path, "w") as f:
        json.dump(cp, f, indent=2)


def _step_done(output_dir: Path, step: str) -> bool:
    cp = _read_checkpoint(output_dir)
    return step in cp and cp[step].get("done", False)


def run_step(step_name: str, output_dir: Path, skip_if_done: bool = True, **kwargs):
    """Run a pipeline step with checkpoint resumability."""
    if skip_if_done and _step_done(output_dir, step_name):
        print(f"\n[SKIP] Step '{step_name}' already completed")
        return

    print(f"\n{'='*60}")
    print(f"  Step: {step_name}")
    print(f"{'='*60}")
    os.makedirs(output_dir, exist_ok=True)
    return _write_checkpoint(output_dir, step_name)


def make_video(storyboard_path: str, mode: str = "video_first",
               skip_prompts: bool = False, audio_only: bool = False,
               video_path: str = None, draw_mode: str = "sketch_first",
               no_hand: bool = False):
    """Main pipeline orchestration."""

    storyboard = _load_storyboard(storyboard_path)
    output_dir = _get_output_dir(storyboard)
    os.makedirs(output_dir, exist_ok=True)

    topic = storyboard.get("meta", {}).get("topic", "untitled")
    meta = storyboard.get("meta", {})
    camera_config = meta.get("camera", {"enabled": True, "maxZoom": 2.5, "transitionMs": 800})
    fps = meta.get("fps", 30)

    print(f"\n{'#'*60}")
    print(f"  Whiteboard Video Pipeline")
    print(f"  Title: {meta.get('title', 'Untitled')}")
    print(f"  Mode: {mode}")
    print(f"  Output: {output_dir}")
    print(f"{'#'*60}")

    # ── Audio-only mode ──
    if audio_only:
        print("\n[Audio-only mode]")
        if not video_path or not os.path.exists(video_path):
            print("ERROR: --video required for audio-only mode")
            sys.exit(1)

        # Step 5: TTS
        if not _step_done(output_dir, "tts"):
            tts_mod = _import_step("tts_pipeline")
            tts_mod.tts_pipeline(storyboard_path, str(output_dir))

        # Step 10: Mix audio
        audio_dir = output_dir / "audio"
        if not _step_done(output_dir, "mix"):
            mixer_mod = _import_step("audio_mixer")
            mixer_mod.mix_all_scenes(storyboard_path, str(audio_dir),
                                     timeline_path=str(output_dir / "timeline.json"))

        # ffmpeg merge audio into video
        merged_path = output_dir / "video.mp4"
        print(f"\n  Merging audio into video...")
        audio_files = sorted(audio_dir.glob("*_mixed.wav"))
        if audio_files:
            # Concat all audio files
            concat_path = output_dir / "_audio_concat.txt"
            with open(concat_path, "w") as f:
                for af in audio_files:
                    f.write(f"file '{af.absolute()}'\n")
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path,
                "-f", "concat", "-safe", "0", "-i", str(concat_path),
                "-c:v", "copy", "-c:a", "aac", "-shortest",
                str(merged_path),
            ], check=True)
            os.remove(concat_path)
            print(f"  Output: {merged_path}")
        return

    # ── Step 0: Validate ──
    if not _step_done(output_dir, "validate"):
        val_mod = _import_step("validate")
        val_mod.run_checks(storyboard_path, check_tts=(mode == "full"))
        _write_checkpoint(output_dir, "validate")

    # ── Step 1: Parse storyboard ──
    if not skip_prompts and not _step_done(output_dir, "parse"):
        parse_mod = _import_step("parse_storyboard")
        parse_mod.parse_storyboard(storyboard_path, str(output_dir / "storyboard.json"),
                                    draw_mode=draw_mode, pipeline_mode=mode)
        _write_checkpoint(output_dir, "parse")

    # ── Step 2: Generate prompts ──
    if not skip_prompts and not _step_done(output_dir, "prompts"):
        prompts_mod = _import_step("generate_prompts")
        prompts_mod.generate_prompts(storyboard, str(output_dir / "prompts.md"))
        _write_checkpoint(output_dir, "prompts")
        print(f"\n  >>> Image prompts generated: {output_dir / 'prompts.md'}")
        print(f"  >>> Generate images using your preferred tool, place in {output_dir / 'images'}/")
        print(f"  >>> Then run with --skip-prompts to continue")
        return  # Pause for user to generate images

    # ── After skip-prompts: continue from here ──

    # ── Step 3: Validate images ──
    images_dir = output_dir / "images"
    if not _step_done(output_dir, "validate_images"):
        val_img_mod = _import_step("validate_images")
        issues = val_img_mod.validate_images(storyboard, str(images_dir))
        # Auto-fix background
        val_img_mod.fix_background_color(str(images_dir))
        _write_checkpoint(output_dir, "validate_images", {"issues": len(issues)})

    # ── Step 5: TTS (full mode only) ──
    tts_data = None
    if mode == "full" or mode == "full":
        if not _step_done(output_dir, "tts"):
            tts_mod = _import_step("tts_pipeline")
            tts_data = tts_mod.tts_pipeline(
                str(output_dir / "storyboard.json"), str(output_dir),
                provider=meta.get("tts", {}).get("provider", "tencent"),
                voice=meta.get("tts", {}).get("voice", 602005),
                speed=meta.get("tts", {}).get("speed", 1.1),
            )
            _write_checkpoint(output_dir, "tts", {"scenes": list(tts_data.keys())})
        else:
            cp = _read_checkpoint(output_dir)
            tts_data = cp.get("tts", {}).get("data", {})

    # ── Step 6: Compute timeline ──
    timeline_path = output_dir / "timeline.json"
    if not _step_done(output_dir, "timeline"):
        timeline_mod = _import_step("compute_timeline")
        timeline = timeline_mod.compute_timeline(
            storyboard_path, str(timeline_path),
            tts_data=tts_data, draw_mode=draw_mode,
            transition_ms=camera_config.get("transitionMs", 800),
            fps=fps,
        )
        _write_checkpoint(output_dir, "timeline", {"totalFrames": timeline["totalFrames"]})
    else:
        with open(timeline_path) as f:
            timeline = json.load(f)

    # ── Step 7: Generate default SFX ──
    if not _step_done(output_dir, "sfx"):
        sfx_mod = _import_step("generate_default_sfx")
        sfx_mod.generate_sfx()
        _write_checkpoint(output_dir, "sfx")

    # ── Step 8: Generate animations ──
    anim_dir = output_dir / "animations"
    if not _step_done(output_dir, "animations"):
        anim_mod = _import_step("generate_animations")
        anim_mod.generate_animations(
            storyboard_path,
            regions_path=str(output_dir / "regions_detected.json"),
            output_dir=str(output_dir),
            camera_config=camera_config,
            draw_hand=not no_hand,
            draw_mode=draw_mode,
        )
        _write_checkpoint(output_dir, "animations")
    else:
        print(f"\n[SKIP] Animations already generated")

    # ── Step 9: Finalize timeline (ffprobe) + generate subtitles ──
    if not _step_done(output_dir, "final_timeline"):
        timeline_mod = _import_step("compute_timeline")
        timeline_mod.finalize_timeline_with_ffprobe(
            str(timeline_path), str(anim_dir), str(timeline_path)
        )
        _write_checkpoint(output_dir, "final_timeline")

    subs_path = output_dir / "subtitles.srt"
    if not _step_done(output_dir, "subtitles"):
        # Reload finalized timeline
        with open(timeline_path) as f:
            timeline = json.load(f)
        subs_mod = _import_step("generate_subtitles")
        subs_mod.generate_srt(timeline, storyboard, str(subs_path))
        _write_checkpoint(output_dir, "subtitles")

    # ── Step 10: Mix audio (full mode only) ──
    if mode == "full":
        if not _step_done(output_dir, "mix"):
            mixer_mod = _import_step("audio_mixer")
            mixer_mod.mix_all_scenes(
                storyboard_path, str(output_dir / "audio"),
                timeline_path=str(timeline_path),
                output_dir=str(output_dir),
            )
            _write_checkpoint(output_dir, "mix")

    # ── Step 11: Deploy resources + Remotion render ──
    video_output = output_dir / ("video.mp4" if mode == "full" else "video_silent.mp4")
    if not _step_done(output_dir, "remotion"):
        # Deploy resources
        deploy_mod = _import_step("deploy_resources")
        deploy_mod.deploy_resources(
            storyboard_path, str(output_dir),
            copy_animations=True,
            copy_audio=(mode == "full"),
        )

        # Remotion render
        remotion_dir = _PROJECT_ROOT / "remotion-project"
        print(f"\n  Rendering with Remotion...")
        result = subprocess.run(
            ["npx", "remotion", "render", "src/index.tsx", "VideoMain",
             str(video_output)],
            cwd=str(remotion_dir),
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  Remotion render complete: {video_output}")
            _write_checkpoint(output_dir, "remotion")
        else:
            print(f"  [ERR] Remotion render failed:")
            print(result.stderr)
            # Continue anyway — user can re-render manually

    # ── Step 12: Generate publish copy ──
    if not _step_done(output_dir, "publish"):
        pub_mod = _import_step("generate_publish")
        pub_mod.generate_publish(storyboard_path, str(output_dir / "publish.md"))
        _write_checkpoint(output_dir, "publish")

    print(f"\n{'='*60}")
    print(f"  Pipeline complete!")
    print(f"  Output: {output_dir}")
    if video_output.exists():
        size_mb = os.path.getsize(video_output) / (1024 * 1024)
        print(f"  Video: {video_output.name} ({size_mb:.1f} MB)")
    print(f"{'='*60}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Whiteboard video pipeline orchestrator")
    parser.add_argument("--storyboard", "-s", required=True, help="Path to storyboard.json")
    parser.add_argument("--mode", default="video_first", choices=["video_first", "full"],
                        help="Pipeline mode")
    parser.add_argument("--skip-prompts", action="store_true",
                        help="Skip prompt generation (continue after images are ready)")
    parser.add_argument("--audio-only", action="store_true",
                        help="Only add audio to existing video")
    parser.add_argument("--video", help="Path to existing video (for audio-only mode)")
    parser.add_argument("--draw-mode", default="sketch_first",
                        choices=["sketch_first", "sequential"])
    parser.add_argument("--no-hand", action="store_true", help="Disable drawing hand")
    args = parser.parse_args()

    make_video(
        storyboard_path=args.storyboard,
        mode=args.mode,
        skip_prompts=args.skip_prompts,
        audio_only=args.audio_only,
        video_path=args.video,
        draw_mode=args.draw_mode,
        no_hand=args.no_hand,
    )


if __name__ == "__main__":
    main()
