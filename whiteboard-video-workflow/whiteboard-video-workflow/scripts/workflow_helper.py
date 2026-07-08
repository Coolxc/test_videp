#!/usr/bin/env python3
"""
Whiteboard Video Workflow Helper

Provides three commands:
  1. init-dirs     - Create storyboard/image/video output directories
  2. gen-prompts   - Parse storyboard.json and generate image prompts with whiteboard style prefix
  3. merge-videos  - Merge video segments into one final video using PyAV

Usage:
    python workflow_helper.py init-dirs <output-dir>
    python workflow_helper.py gen-prompts <storyboard-json-path>
    python workflow_helper.py merge-videos <output-dir> [--hook-clip <hook-path>] <video1> <video2> ...
    python workflow_helper.py generate-audio <storyboard-json> <assets-dir> <voice-dir> <output-mp3>
"""

import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

class FatalError(Exception):
    pass



def ends_with_symbol(text: str) -> bool:
    """Return True when the stripped text already ends with punctuation or a symbol."""
    stripped = text.rstrip()
    if not stripped:
        return False
    return unicodedata.category(stripped[-1])[0] in {"P", "S"}


def ensure_ending(text: str, ending: str) -> str:
    """Append ending only when the stripped text does not already end with a symbol."""
    stripped = text.strip()
    if not stripped:
        return ""
    if ends_with_symbol(stripped):
        return stripped
    return f"{stripped}{ending}"


def join_scene_text(text_parts: list[str]) -> str:
    """Join scene segment texts while preserving existing ending symbols."""
    parts = [text.strip() for text in text_parts if text.strip()]
    if not parts:
        return ""

    pieces = [ensure_ending(text, "，") for text in parts[:-1]]
    pieces.append(ensure_ending(parts[-1], "。"))
    return "".join(pieces)


def init_dirs(output_dir: str):
    """Create storyboard, image, video subdirectories under output_dir."""
    base = Path(output_dir).resolve()
    for name in ("storyboard", "image", "video"):
        (base / name).mkdir(parents=True, exist_ok=True)
    print(json.dumps({
        "status": "ok",
        "storyboardDir": str(base / "storyboard"),
        "imageDir": str(base / "image"),
        "videoDir": str(base / "video"),
    }))


def gen_prompts(storyboard_path: str):
    """Parse storyboard.json and output a JSON array of image prompts."""
    sb = json.loads(Path(storyboard_path).read_text(encoding="utf-8"))
    prompts = []
    for scene in sb.get("scenes", []):
        # Concatenate all segment texts
        text_parts = [seg["text"] for seg in scene.get("segments", [])]
        full_text = join_scene_text(text_parts)
        # Append visualHint
        visual_hint = ensure_ending(scene.get("visualHint", ""), "。")
        if visual_hint:
            content = f'以下是我的内容：\n"{full_text}"\n\n视觉元素建议：\n"{visual_hint}"'
        else:
            content = f'以下是我的内容：\n"{full_text}"'
        prompt = content
        prompts.append(prompt)
    print(json.dumps(prompts, ensure_ascii=False))


def merge_videos(output_dir: str, video_paths: list[str], hook_clip: str = None):
    """Merge multiple video segments into one final video using PyAV (re-encode via H.264)."""
    # Prepend hook clip if provided
    all_videos = []
    if hook_clip:
        all_videos.append(hook_clip)
    all_videos.extend(video_paths)
    
    if not all_videos:
        print(json.dumps({"status": "error", "error": "没有视频片段可合并"}))
        sys.exit(1)

    # 检查所有视频文件是否存在
    for vp in all_videos:
        if not Path(vp).exists():
            print(json.dumps({"status": "error", "error": f"视频文件不存在: {vp}"}))
            sys.exit(1)

    # 生成输出路径
    output_path = Path(output_dir).resolve()
    if not output_path.name.lower().endswith(".mp4"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_path / f"merged_{timestamp}.mp4"
    
    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    import av
    from fractions import Fraction

    try:
        # 从第一个片段获取编码参数
        first_input = av.open(all_videos[0], mode="r")
        if not first_input.streams.video:
            raise FatalError(f"视频无画面流: {all_videos[0]}")
        in_stream = first_input.streams.video[0]
        width = in_stream.codec_context.width
        height = in_stream.codec_context.height
        fps = in_stream.average_rate
        first_input.close()

        # 创建输出容器
        time_base = Fraction(1, int(fps))

        output_container = av.open(str(output_path), mode="w")
        out_stream = output_container.add_stream("h264", rate=fps)
        out_stream.width = width
        out_stream.height = height
        out_stream.pix_fmt = "yuv420p"
        out_stream.time_base = time_base
        out_stream.options = {"crf": "18"}

        # 逐个读取输入片段，解码后重新编码写入输出
        # 使用帧计数器生成单调递增的 PTS，避免多段拼接时时间戳倒退
        frame_count = 0
        for vp in all_videos:
            input_container = av.open(vp, mode="r")
            for frame in input_container.decode(video=0):
                frame.pts = frame_count
                frame.time_base = time_base
                frame_count += 1
                packet = out_stream.encode(frame)
                if packet:
                    for p in packet:
                        output_container.mux(p)
            input_container.close()

        # flush
        packet = out_stream.encode(None)
        if packet:
            for p in packet:
                output_container.mux(p)
        output_container.close()
    except Exception as e:
        # 清理可能残留的输出文件
        if output_path.exists():
            output_path.unlink()
        print(json.dumps({"status": "error", "error": f"视频合并失败: {e}"}))
        sys.exit(1)

    output_size_mb = output_path.stat().st_size / (1024 * 1024)
    print(json.dumps({
        "status": "ok",
        "mergedVideo": str(output_path),
        "totalSegments": len(video_paths),
        "sizeMB": round(output_size_mb, 1),
    }, ensure_ascii=False))

def generate_audio(data_path, assets_dir, voice_dir, output_path):
    """Call the shorts-audio-engine skill to generate the final mix."""
    import subprocess
    audio_engine_path = Path("/Users/max/code/whiteboard-animation-skill/shorts-audio-engine")
    venv_python = audio_engine_path / ".venv" / "bin" / "python"
    pipeline_script = audio_engine_path / "scripts" / "pipeline.py"
    
    cmd = [
        str(venv_python), str(pipeline_script),
        "--data", str(data_path),
        "--assets", str(assets_dir),
        "--voice-dir", str(voice_dir),
        "--output", str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(json.dumps({"status": "error", "error": f"Audio generation failed: {e.stderr}"}))
        sys.exit(1)


def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  workflow_helper.py init-dirs <output-dir>")
        print("  workflow_helper.py gen-prompts <storyboard-json-path>")
        print("  workflow_helper.py merge-videos <output-dir> <video1> <video2> ...")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "init-dirs":
        init_dirs(sys.argv[2])
    elif cmd == "gen-prompts":
        gen_prompts(sys.argv[2])
    elif cmd == "merge-videos":
        if len(sys.argv) < 4:
            print("Error: merge-videos requires output-dir and at least one video path")
            sys.exit(1)
        
        args = sys.argv[2:]
        output_dir = args[0]
        hook_clip = None
        video_paths = []
        
        i = 1
        while i < len(args):
            if args[i] == "--hook-clip" and i + 1 < len(args):
                hook_clip = args[i+1]
                i += 2
            else:
                video_paths.append(args[i])
                i += 1
                
        merge_videos(output_dir, video_paths, hook_clip)
    elif cmd == "generate-audio":
        if len(sys.argv) < 6:
            print("Error: generate-audio requires data_path, assets_dir, voice_dir and output_path")
            sys.exit(1)
        generate_audio(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
