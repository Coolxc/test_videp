#!/usr/bin/env python3
"""
generate_scene_animation.py - Camera-driven whiteboard hand-drawn animation engine.

Wraps the core generate_whiteboard.py functions with:
  - CameraVideoWriter (virtual camera with viewport cropping + zoom)
  - Sketch-first / sequential draw modes
  - Dip / breathe transitions between elements
  - Adaptive brush radius (reverse-scaled by zoom)
  - Path coherence checking + nearest-neighbor reordering
  - Hand image caching + multi-resolution scaling
  - Ken Burns hold micro-movement
  - End transition (alpha blend + zoom-out)

Usage:
  from generate_scene_animation import generate_scene_with_regions
"""

import json
import os
import sys
import time

import cv2
import numpy as np
from config import ENGINE_SCRIPTS_DIR, validate_engine


# ── Path setup: import from whiteboard-animation engine ──
sys.path.insert(0, str(ENGINE_SCRIPTS_DIR))

engine_errors = validate_engine()
if engine_errors:
    for e in engine_errors:
        print(f"  [ERR] {e}")
    raise RuntimeError("Animation engine validation failed. Run validate.py for details.")

from generate_whiteboard import (
    preprocess_image, preprocess_hand_image, split_image_into_cells,
    extract_active_grid, build_layout_blocks, build_draw_order,
    draw_masked_object, colorize_animation, create_background_canvas,
    ffmpeg_convert, FRAME_RATE, SPLIT_LEN, SKIP_RATE, HAND_PATH,
    SKETCH_PHASE_WEIGHT, COLOR_PHASE_WEIGHT, BLACK_PIXEL_THRESHOLD,
    COLOR_BRUSH_RADIUS, HAND_TARGET_HT,
)

# ── Override: use max_dim=1920 instead of engine's 1080 ──
MAX_DIM = 1920
OUTPUT_W, OUTPUT_H = 1920, 1080
HAND_TARGET_HT = 493  # Keep engine default as base

# Colorize acceleration
COLOR_SKIP_MULTIPLIER = 1.5

# Ken Burns
HOLD_KEN_BURNS_START_ZOOM = 0.97

BACKGROUND_BGR = np.array([227, 241, 246], dtype=np.uint8)  # #F6F1E3 in BGR

# ── Hand cache (module-level, persists across scenes) ──
_hand_cache = {}


def load_hand_once(hand_path, variables):
    """Load hand image once at base resolution, cache it."""
    preprocess_hand_image(hand_path, variables)
    _hand_cache[HAND_TARGET_HT] = {
        k: variables[k].copy() if isinstance(variables[k], np.ndarray) else variables[k]
        for k in ("hand", "hand_mask", "hand_mask_inv", "hand_ht", "hand_wd")
    }


def scale_hand_for_zoom(variables, zoom_ratio):
    """Scale cached hand image to current zoom level."""
    target_ht = max(100, int(HAND_TARGET_HT * zoom_ratio))
    if target_ht in _hand_cache:
        variables.update(_hand_cache[target_ht])
        return variables

    if HAND_TARGET_HT not in _hand_cache:
        return variables  # No base cached

    orig = _hand_cache[HAND_TARGET_HT]
    ratio = target_ht / orig["hand_ht"]
    new_w = max(1, int(orig["hand_wd"] * ratio))

    variables["hand"] = cv2.resize(orig["hand"], (new_w, target_ht), interpolation=cv2.INTER_AREA)
    variables["hand_mask"] = cv2.resize(orig["hand_mask"], (new_w, target_ht), interpolation=cv2.INTER_AREA)
    variables["hand_mask_inv"] = 1.0 - variables["hand_mask"]
    variables["hand_ht"], variables["hand_wd"] = target_ht, new_w

    _hand_cache[target_ht] = {
        k: variables[k].copy() if isinstance(variables[k], np.ndarray) else variables[k]
        for k in ("hand", "hand_mask", "hand_mask_inv", "hand_ht", "hand_wd")
    }
    return variables


# ── CameraVideoWriter ──
class CameraVideoWriter:
    """Wrap cv2.VideoWriter, applying viewport crop + zoom on each frame."""

    def __init__(self, real_writer, canvas_w, canvas_h, output_w=OUTPUT_W, output_h=OUTPUT_H):
        self.writer = real_writer
        self.canvas_w, self.canvas_h = canvas_w, canvas_h
        self.output_w, self.output_h = output_w, output_h
        self.viewport = None  # None = full canvas
        self._frame_count = 0

    def set_viewport(self, vp):
        self.viewport = vp

    @property
    def frame_count(self):
        return self._frame_count

    def write(self, frame):
        self._frame_count += 1
        if self.viewport:
            vp = self.viewport
            # Clamp to canvas bounds
            y1 = max(0, vp["y"])
            y2 = min(self.canvas_h, vp["y"] + vp["h"])
            x1 = max(0, vp["x"])
            x2 = min(self.canvas_w, vp["x"] + vp["w"])
            cropped = frame[y1:y2, x1:x2]
            frame = cv2.resize(cropped, (self.output_w, self.output_h),
                               interpolation=cv2.INTER_LANCZOS4)
        elif frame.shape[1] != self.output_w or frame.shape[0] != self.output_h:
            frame = cv2.resize(frame, (self.output_w, self.output_h),
                               interpolation=cv2.INTER_LANCZOS4)
        self.writer.write(frame)

    def release(self):
        self.writer.release()


# ── Viewport computation ──
def compute_adaptive_padding(bbox_area, canvas_area):
    """Compute viewport padding based on element size ratio."""
    area_ratio = bbox_area / max(1, canvas_area)
    return 0.20 + 0.30 * min(1.0, area_ratio / 0.30)


def compute_element_viewport(scaled_bbox, canvas_w, canvas_h, max_zoom=2.5):
    """Compute optimal viewport centered on element with adaptive padding."""
    cx = scaled_bbox["x"] + scaled_bbox["w"] / 2
    cy = scaled_bbox["y"] + scaled_bbox["h"] / 2
    bbox_area = scaled_bbox["w"] * scaled_bbox["h"]
    padding = compute_adaptive_padding(bbox_area, canvas_w * canvas_h)

    vw = scaled_bbox["w"] * max(1.0, 1 + 2 * padding)
    vh = scaled_bbox["h"] * max(1.0, 1 + 2 * padding)

    # Force 16:9
    if vw / vh > 16 / 9:
        vh = vw / (16 / 9)
    else:
        vw = vh * (16 / 9)

    # Clamp to max zoom
    vw = max(canvas_w / max_zoom, min(vw, canvas_w))
    vh = max(canvas_h / max_zoom, min(vh, canvas_h))

    vx = int(max(0, min(cx - vw / 2, canvas_w - vw)))
    vy = int(max(0, min(cy - vh / 2, canvas_h - vh)))

    return {"x": vx, "y": vy, "w": int(vw), "h": int(vh)}


def ease_in_out(t):
    """Smoothstep interpolation."""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def interpolate_viewport(vp1, vp2, t):
    """Linearly interpolate between two viewports with ease-in-out."""
    t = ease_in_out(max(0.0, min(1.0, t)))
    return {
        "x": int(vp1["x"] + (vp2["x"] - vp1["x"]) * t),
        "y": int(vp1["y"] + (vp2["y"] - vp1["y"]) * t),
        "w": int(vp1["w"] + (vp2["w"] - vp1["w"]) * t),
        "h": int(vp1["h"] + (vp2["h"] - vp1["h"]) * t),
    }


# ── Transition strategies ──
def choose_transition_strategy(current_vp, target_vp, canvas_w, canvas_h, phase):
    """Choose dip or breathe based on phase and distance."""
    if phase == "sketch":
        return "dip"

    cx1 = current_vp["x"] + current_vp["w"] / 2
    cy1 = current_vp["y"] + current_vp["h"] / 2
    cx2 = target_vp["x"] + target_vp["w"] / 2
    cy2 = target_vp["y"] + target_vp["h"] / 2
    distance = ((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2) ** 0.5
    canvas_diag = (canvas_w ** 2 + canvas_h ** 2) ** 0.5

    return "dip" if distance / canvas_diag > 0.4 else "breathe"


def write_dip_transition(camera_writer, drawn_frame, current_vp, target_vp, dip_frames):
    """Fade to background → jump viewport → hold clean background."""
    frame = drawn_frame if drawn_frame.dtype == np.uint8 else drawn_frame.astype(np.uint8)
    bg = np.full_like(frame, BACKGROUND_BGR, dtype=np.uint8)

    fade_out_frames = dip_frames * 2 // 3
    for f in range(fade_out_frames):
        t = ((f + 1) / max(1, fade_out_frames)) ** 2
        blended = cv2.addWeighted(frame, 1 - t, bg, t, 0)
        camera_writer.set_viewport(current_vp)
        camera_writer.write(blended)

    camera_writer.set_viewport(target_vp)
    hold_frames = dip_frames - fade_out_frames
    for _ in range(hold_frames):
        camera_writer.write(bg)


def compute_breathe_viewport(current_vp, target_vp, canvas_w, canvas_h):
    """Compute a viewport that contains both current and target."""
    x_min = min(current_vp["x"], target_vp["x"])
    y_min = min(current_vp["y"], target_vp["y"])
    x_max = max(current_vp["x"] + current_vp["w"], target_vp["x"] + target_vp["w"])
    y_max = max(current_vp["y"] + current_vp["h"], target_vp["y"] + target_vp["h"])

    pad = 0.15
    w = (x_max - x_min) * (1 + 2 * pad)
    h = (y_max - y_min) * (1 + 2 * pad)

    if w / h > 16 / 9:
        h = w / (16 / 9)
    else:
        w = h * (16 / 9)

    w, h = min(w, canvas_w), min(h, canvas_h)

    cx, cy = (x_min + x_max) / 2, (y_min + y_max) / 2
    x = int(max(0, min(cx - w / 2, canvas_w - w)))
    y = int(max(0, min(cy - h / 2, canvas_h - h)))

    return {"x": x, "y": y, "w": int(w), "h": int(h)}


def write_breathe_transition(camera_writer, drawn_frame, current_vp, target_vp,
                              canvas_w, canvas_h, breathe_frames):
    """Zoom out to intermediate viewport → zoom in to target."""
    frame = drawn_frame if drawn_frame.dtype == np.uint8 else drawn_frame.astype(np.uint8)
    breathe_vp = compute_breathe_viewport(current_vp, target_vp, canvas_w, canvas_h)
    half = breathe_frames // 2

    for f in range(half):
        t = (f + 1) / max(1, half)
        camera_writer.set_viewport(interpolate_viewport(current_vp, breathe_vp, t))
        camera_writer.write(frame)
    for f in range(breathe_frames - half):
        t = (f + 1) / max(1, breathe_frames - half)
        camera_writer.set_viewport(interpolate_viewport(breathe_vp, target_vp, t))
        camera_writer.write(frame)


# ── Brush radius ──
def compute_adjusted_brush_radius(viewport_w, canvas_w, base_radius=COLOR_BRUSH_RADIUS):
    """Scale brush radius so visual size is constant regardless of zoom."""
    zoom_ratio = viewport_w / max(1, canvas_w)
    return max(15, int(base_radius * zoom_ratio))


# ── Path coherence ──
def check_path_coherence(cells):
    """Calculate average step distance in a draw path."""
    if len(cells) <= 1:
        return 0.0
    total = sum(
        ((cells[i][0] - cells[i - 1][0]) ** 2 + (cells[i][1] - cells[i - 1][1]) ** 2) ** 0.5
        for i in range(1, len(cells))
    )
    return total / (len(cells) - 1)


def reorder_nearest_neighbor(cells):
    """Greedy nearest-neighbor reorder using KDTree."""
    if len(cells) <= 2:
        return cells
    try:
        from scipy.spatial import KDTree
        coords = np.array(cells)
        tree = KDTree(coords)
        start_idx = int(np.argmin(coords[:, 0] * 1000 + coords[:, 1]))

        visited = np.zeros(len(cells), dtype=bool)
        result = [start_idx]
        visited[start_idx] = True

        for _ in range(len(cells) - 1):
            _, indices = tree.query(coords[result[-1]], k=min(20, len(cells)))
            next_idx = next((i for i in indices if not visited[i]), None)
            if next_idx is None:
                next_idx = next((i for i in range(len(cells)) if not visited[i]), None)
            if next_idx is None:
                break
            result.append(next_idx)
            visited[next_idx] = True

        return [cells[i] for i in result]
    except ImportError:
        print("    [WARN] scipy not available, skipping nearest-neighbor reorder")
        return cells


def ensure_path_coherence(cells, threshold=3.0):
    """Only reorder if avg step exceeds threshold; preserve engine's strategy otherwise."""
    if len(cells) <= 2:
        return cells
    avg_step = check_path_coherence(cells)
    if avg_step <= threshold:
        return cells
    print(f"    Path coherence fix: avg_step={avg_step:.1f} > {threshold}, "
          f"reordering {len(cells)} cells via nearest-neighbor")
    return reorder_nearest_neighbor(cells)


def filter_draw_order_for_bbox(full_draw_order, scaled_bbox, padding_ratio=0.10):
    """Filter draw order to cells within a bounding box, with padding to prevent edge truncation.

    padding_ratio: bbox 尺寸的百分比作为额外边距，默认 10%。
    最小 padding 为 2 个 grid cell（20px at SPLIT_LEN=10）。
    """
    pad_x = max(2, int(scaled_bbox["w"] * padding_ratio / SPLIT_LEN))
    pad_y = max(2, int(scaled_bbox["h"] * padding_ratio / SPLIT_LEN))

    x_min = max(0, scaled_bbox["x"] // SPLIT_LEN - pad_x)
    y_min = max(0, scaled_bbox["y"] // SPLIT_LEN - pad_y)
    x_max = (scaled_bbox["x"] + scaled_bbox["w"]) // SPLIT_LEN + pad_x
    y_max = (scaled_bbox["y"] + scaled_bbox["h"]) // SPLIT_LEN + pad_y

    return [
        cell for cell in full_draw_order
        if y_min <= cell[0] <= y_max and x_min <= cell[1] <= x_max
    ]


# ── Ken Burns hold ──
def write_hold_with_ken_burns(camera_writer, img_resized, canvas_w, canvas_h, hold_frames):
    """Write hold frames with subtle Ken Burns zoom (97% → 100%)."""
    for f in range(hold_frames):
        t = ease_in_out(f / max(1, hold_frames - 1))
        zoom = HOLD_KEN_BURNS_START_ZOOM + (1.0 - HOLD_KEN_BURNS_START_ZOOM) * t
        w, h = int(canvas_w * zoom), int(canvas_h * zoom)
        x, y = (canvas_w - w) // 2, (canvas_h - h) // 2
        camera_writer.set_viewport({"x": x, "y": y, "w": w, "h": h})
        camera_writer.write(img_resized)


def _count_written_frames(camera_writer):
    """Get total frames written by CameraVideoWriter."""
    return getattr(camera_writer, "frame_count", 0)


# ── Main entry point ──
def generate_scene_with_regions(image_path, regions, total_duration_ms, output_dir,
                                 camera_config=None, draw_hand=True, draw_mode="sketch_first"):
    """
    Generate a whiteboard hand-drawn animation for one scene.

    Args:
        image_path: Path to source image.
        regions: List of dicts with "bbox" and optionally "drawAt", "durationMs".
        total_duration_ms: Total scene duration in milliseconds.
        output_dir: Output directory for video files.
        camera_config: Dict with {"enabled", "maxZoom", "transitionMs"}.
        draw_hand: Whether to overlay the drawing hand.
        draw_mode: "sketch_first" or "sequential".

    Returns:
        Path to the rendered H.264 MP4 file.
    """
    camera_enabled = camera_config.get("enabled", True) if camera_config else True
    max_zoom = camera_config.get("maxZoom", 2.5) if camera_config else 2.5
    transition_ms = camera_config.get("transitionMs", 800) if camera_config else 800

    # ── 1. Read + resize image ──
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        raise ValueError(f"Cannot read image: {image_path}")

    orig_h, orig_w = img_bgr.shape[:2]
    scale = MAX_DIM / max(orig_w, orig_h)
    lcm = SPLIT_LEN if SPLIT_LEN % 2 == 0 else SPLIT_LEN * 2
    resize_wd = (int(orig_w * scale) // lcm) * lcm
    resize_ht = (int(orig_h * scale) // lcm) * lcm

    # Scale bbox coordinates
    sx, sy = resize_wd / max(1, orig_w), resize_ht / max(1, orig_h)
    for region in regions:
        b = region.get("bbox", {})
        region["scaled_bbox"] = {
            "x": int(b.get("x", 0) * sx),
            "y": int(b.get("y", 0) * sy),
            "w": int(b.get("w", orig_w) * sx),
            "h": int(b.get("h", orig_h) * sy),
        }

    print(f"  Canvas: {resize_wd}x{resize_ht}, scale={scale:.3f}, grid={resize_wd // SPLIT_LEN}x{resize_ht // SPLIT_LEN}")

    # ── Initialize engine variables ──
    variables = {
        "split_len": SPLIT_LEN,
        "resize_wd": resize_wd,
        "resize_ht": resize_ht,
        "draw_hand": draw_hand,
    }

    img_resized = cv2.resize(img_bgr, (resize_wd, resize_ht))
    variables["img"] = img_resized
    variables = preprocess_image(img_resized, variables)
    variables["grid_of_cuts"] = split_image_into_cells(variables["img_thresh"], SPLIT_LEN)
    active_grid, _ = extract_active_grid(variables["img_thresh"], SPLIT_LEN)
    variables["active_grid"] = active_grid
    layout_blocks = build_layout_blocks(active_grid)
    full_draw_order = build_draw_order(active_grid, layout_blocks=layout_blocks)

    print(f"  Layout blocks: {len(layout_blocks)}, draw cells: {len(full_draw_order)}")

    # ── 2. Precompute viewports / filtered orders / brush radii ──
    sorted_regions = sorted(regions, key=lambda r: r.get("drawAt") if r.get("drawAt") is not None else 0)
    full_vp = {"x": 0, "y": 0, "w": resize_wd, "h": resize_ht}

    for region in sorted_regions:
        region["_viewport"] = compute_element_viewport(
            region["scaled_bbox"], resize_wd, resize_ht, max_zoom
        )
        raw_order = filter_draw_order_for_bbox(full_draw_order, region["scaled_bbox"])
        region["_draw_order"] = ensure_path_coherence(raw_order) if camera_enabled else raw_order
        region["_brush_radius"] = compute_adjusted_brush_radius(
            region["_viewport"]["w"], resize_wd
        )

        vp = region["_viewport"]
        print(f"    Region '{region.get('id', '?')}': viewport={vp['w']}x{vp['h']} "
              f"at ({vp['x']},{vp['y']}), cells={len(region['_draw_order'])}, "
              f"brush_r={region['_brush_radius']}")

    # ── 3. VideoWriter setup ──
    os.makedirs(output_dir, exist_ok=True)
    ts = int(time.time())
    raw_path = os.path.join(output_dir, f"raw_{ts}.mp4")
    h264_path = os.path.join(output_dir, f"vid_{ts}_h264.mp4")

    real_writer = cv2.VideoWriter(raw_path, cv2.VideoWriter_fourcc(*"mp4v"),
                                  FRAME_RATE, (OUTPUT_W, OUTPUT_H))
    camera_writer = CameraVideoWriter(real_writer, resize_wd, resize_ht, OUTPUT_W, OUTPUT_H)

    variables["video_object"] = camera_writer
    variables["drawn_frame"] = create_background_canvas(img_resized.shape)

    if draw_hand:
        load_hand_once(HAND_PATH, variables)

    colorize_skip = int(SKIP_RATE * COLOR_SKIP_MULTIPLIER)
    n = len(sorted_regions)

    # ── Helper: per-element frame allocation ──
    def get_phase_frames(region):
        elem_ms = region.get("durationMs", 3000)
        sketch_ms = elem_ms * SKETCH_PHASE_WEIGHT / (SKETCH_PHASE_WEIGHT + COLOR_PHASE_WEIGHT)
        sf = max(1, round(sketch_ms * FRAME_RATE / 1000))
        cf = max(1, round((elem_ms - sketch_ms) * FRAME_RATE / 1000))
        return sf, cf

    def do_transition(current_vp, target_vp, phase):
        strategy = choose_transition_strategy(current_vp, target_vp, resize_wd, resize_ht, phase)
        trans_frames = round(transition_ms * FRAME_RATE / 1000)
        frame = variables["drawn_frame"]
        frame = frame if frame.dtype == np.uint8 else frame.astype(np.uint8)

        if strategy == "dip":
            write_dip_transition(camera_writer, frame, current_vp, target_vp, trans_frames)
        else:
            write_breathe_transition(camera_writer, frame, current_vp, target_vp,
                                      resize_wd, resize_ht, trans_frames)

    # ── 4. Drawing ──
    current_viewport = full_vp
    print(f"\n  Draw mode: {draw_mode} ({n} elements)")

    if draw_mode == "sketch_first" and n > 1:
        # ── Pass 1: All sketches ──
        print("  Pass 1: Sketch (all elements)...")
        for idx, region in enumerate(sorted_regions):
            target_vp = region["_viewport"]
            if idx == 0:
                camera_writer.set_viewport(target_vp)
            else:
                do_transition(current_viewport, target_vp, phase="sketch")

            if draw_hand:
                scale_hand_for_zoom(variables, target_vp["w"] / resize_wd)

            variables["draw_order"] = region["_draw_order"]
            if region["_draw_order"]:
                sketch_frames, _ = get_phase_frames(region)
                draw_masked_object(variables, sketch_frames * SKIP_RATE, skip_rate=SKIP_RATE)
            current_viewport = target_vp

        # ── Phase transition (sketch → colorize) ──
        phase_trans_frames = round(transition_ms * 1.5 * FRAME_RATE / 1000)
        first_vp = sorted_regions[0]["_viewport"]
        frame = variables["drawn_frame"]
        frame = frame if frame.dtype == np.uint8 else frame.astype(np.uint8)
        write_dip_transition(camera_writer, frame, current_viewport, first_vp, phase_trans_frames)
        current_viewport = first_vp
        print(f"  Phase transition: sketch → colorize ({phase_trans_frames} frames)")

        # ── Pass 2: All colorize ──
        print("  Pass 2: Colorize (all elements)...")
        for idx, region in enumerate(sorted_regions):
            target_vp = region["_viewport"]
            if idx > 0:
                do_transition(current_viewport, target_vp, phase="colorize")

            if draw_hand:
                scale_hand_for_zoom(variables, target_vp["w"] / resize_wd)

            camera_writer.set_viewport(target_vp)
            variables["draw_order"] = region["_draw_order"]
            if region["_draw_order"]:
                _, color_frames = get_phase_frames(region)
                colorize_animation(variables, color_frames * colorize_skip,
                                   skip_rate=colorize_skip,
                                   brush_radius=region["_brush_radius"])
                # Constraint 20: always convert back to uint8 after colorize
                if variables["drawn_frame"].dtype != np.uint8:
                    variables["drawn_frame"] = variables["drawn_frame"].astype(np.uint8)
            current_viewport = target_vp

    else:
        # ── Sequential mode (single element or user choice) ──
        print("  Sequential mode...")
        for idx, region in enumerate(sorted_regions):
            target_vp = region["_viewport"]
            if idx == 0:
                camera_writer.set_viewport(target_vp)
            else:
                do_transition(current_viewport, target_vp, phase="colorize")

            if draw_hand:
                scale_hand_for_zoom(variables, target_vp["w"] / resize_wd)

            variables["draw_order"] = region["_draw_order"]
            if region["_draw_order"]:
                sketch_frames, color_frames = get_phase_frames(region)
                draw_masked_object(variables, sketch_frames * SKIP_RATE, skip_rate=SKIP_RATE)
                colorize_animation(variables, color_frames * colorize_skip,
                                   skip_rate=colorize_skip,
                                   brush_radius=region["_brush_radius"])
                if variables["drawn_frame"].dtype != np.uint8:
                    variables["drawn_frame"] = variables["drawn_frame"].astype(np.uint8)
            current_viewport = target_vp

    # ── 5. End transition + Hold ──
    print("  End transition + hold...")
    drawn_frame_uint8 = variables["drawn_frame"]
    drawn_frame_uint8 = drawn_frame_uint8 if drawn_frame_uint8.dtype == np.uint8 else drawn_frame_uint8.astype(np.uint8)

    blend_zoom_frames = 90
    elapsed_frames = _count_written_frames(camera_writer)
    total_frames_target = round(total_duration_ms * FRAME_RATE / 1000)
    total_end_frames = max(blend_zoom_frames + 60, total_frames_target - elapsed_frames)
    actual_blend_frames = min(blend_zoom_frames, total_end_frames)

    # Alpha blend + zoom-out
    for f in range(actual_blend_frames):
        t = (f + 1) / max(1, actual_blend_frames)
        blended = cv2.addWeighted(drawn_frame_uint8, 1 - t ** 0.5, img_resized, t ** 0.5, 0)
        vp = interpolate_viewport(current_viewport, full_vp, t ** 2)
        camera_writer.set_viewport(vp)
        camera_writer.write(blended)

    # Ken Burns hold
    hold_frames_left = total_end_frames - actual_blend_frames
    write_hold_with_ken_burns(camera_writer, img_resized, resize_wd, resize_ht, hold_frames_left)

    # ── 6. Release + H.264 transcode ──
    camera_writer.release()
    print(f"  Total frames written: {elapsed_frames + total_end_frames}")

    if os.path.exists(h264_path):
        os.remove(h264_path)  # Ensure clean conversion

    if ffmpeg_convert(raw_path, h264_path):
        os.remove(raw_path)
        final_path = h264_path
    else:
        print("  [WARN] H.264 conversion failed, keeping raw file")
        final_path = raw_path

    # Rename to scene_final.mp4 convention
    final_renamed = os.path.join(output_dir, "scene_final.mp4")
    if os.path.exists(final_path):
        if os.path.exists(final_renamed):
            os.remove(final_renamed)
        os.rename(final_path, final_renamed)

    print(f"  Output: {final_renamed}")
    return final_renamed
