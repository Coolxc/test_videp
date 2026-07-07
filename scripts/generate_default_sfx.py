#!/usr/bin/env python3
"""
generate_default_sfx.py - Programmatically generate synthetic sound effects.

Zero external dependencies beyond numpy + pydub.
Generates pen sketching and marker coloring sounds on first run.

Output files (auto-skipped if already exist):
  - pen_sketch.mp3: Band-pass filtered white noise with irregular amplitude envelope
  - marker_color.mp3: Low-pass filtered white noise with smooth envelope

Both have crossfade-ready loops.
"""

import os
import sys
from pathlib import Path

import numpy as np


def _ensure_pydub():
    try:
        from pydub import AudioSegment
        return AudioSegment
    except ImportError:
        print("pydub not installed, installing...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pydub"])
        from pydub import AudioSegment
        return AudioSegment


def _band_pass(samples, sample_rate, low_freq, high_freq, order=4):
    """Simple band-pass filter using FFT."""
    fft = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), 1 / sample_rate)
    fft[(freqs < low_freq) | (freqs > high_freq)] = 0
    return np.fft.irfft(fft, len(samples)).astype(np.float32)


def _low_pass(samples, sample_rate, cutoff_freq, order=4):
    """Simple low-pass filter using FFT."""
    fft = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), 1 / sample_rate)
    fft[freqs > cutoff_freq] = 0
    return np.fft.irfft(fft, len(samples)).astype(np.float32)


def _apply_envelope(samples, envelope_type="irregular"):
    """Apply amplitude envelope."""
    n = len(samples)
    t = np.linspace(0, 1, n)

    if envelope_type == "irregular":
        # Irregular: multiple peaks with random amplitudes
        envelope = np.ones(n)
        num_peaks = np.random.randint(3, 7)
        for _ in range(num_peaks):
            peak_pos = np.random.randint(0, n)
            peak_width = np.random.randint(n // 10, n // 3)
            peak_amp = np.random.uniform(0.3, 0.9)
            envelope *= 1.0 + peak_amp * np.exp(-((t - peak_pos / n) ** 2) / (2 * (peak_width / n) ** 2))
        envelope = envelope / envelope.max() * 0.5
    elif envelope_type == "smooth":
        # Smooth: gradual attack and decay
        attack = np.linspace(0, 1, n // 10)
        decay = np.linspace(1, 0.3, n // 5)
        sustain = np.ones(n - len(attack) - len(decay)) * 0.3
        envelope = np.concatenate([attack, sustain, decay])
        envelope = envelope[:n]
    else:
        envelope = np.ones(n) * 0.3

    return (samples * envelope).astype(np.float32)


def generate_pen_sketch(duration_ms: int = 2000, sample_rate: int = 44100) -> bytes:
    """Generate pen sketching sound (band-pass filtered noise + irregular envelope)."""
    np.random.seed(42)  # Deterministic output

    n_samples = int(sample_rate * duration_ms / 1000)
    noise = np.random.randn(n_samples).astype(np.float32)

    # Band-pass filter: 2-8 kHz (pencil scratch frequencies)
    filtered = _band_pass(noise, sample_rate, 2000, 8000)

    # Irregular amplitude envelope
    enveloped = _apply_envelope(filtered, "irregular")

    # Normalize
    enveloped = enveloped / (np.max(np.abs(enveloped)) + 1e-8) * 0.3

    # Crossfade start/end for looping
    fade_len = int(0.05 * sample_rate)
    enveloped[:fade_len] *= np.linspace(0, 1, fade_len)
    enveloped[-fade_len:] *= np.linspace(1, 0, fade_len)

    return (enveloped * 32767).astype(np.int16).tobytes()


def generate_marker_color(duration_ms: int = 2000, sample_rate: int = 44100) -> bytes:
    """Generate marker coloring sound (low-pass filtered noise + smooth envelope)."""
    np.random.seed(43)  # Different seed from pen

    n_samples = int(sample_rate * duration_ms / 1000)
    noise = np.random.randn(n_samples).astype(np.float32)

    # Low-pass filter: 500-3 kHz (marker sweep)
    filtered = _low_pass(noise, sample_rate, 3000)

    # Smooth envelope
    enveloped = _apply_envelope(filtered, "smooth")

    # Normalize (quieter than pen - marker sound is softer)
    enveloped = enveloped / (np.max(np.abs(enveloped)) + 1e-8) * 0.15

    # Crossfade
    fade_len = int(0.05 * sample_rate)
    enveloped[:fade_len] *= np.linspace(0, 1, fade_len)
    enveloped[-fade_len:] *= np.linspace(1, 0, fade_len)

    return (enveloped * 32767).astype(np.int16).tobytes()


def generate_sfx(output_dir: str = None, force: bool = False) -> dict[str, str]:
    """Generate default SFX files. Returns dict of {name: path}."""
    AudioSegment = _ensure_pydub()

    if output_dir is None:
        output_dir = str(Path(__file__).resolve().parent.parent / "remotion-project" / "public" / "assets" / "sfx")

    os.makedirs(output_dir, exist_ok=True)

    sfx_files = {
        "pen_sketch": os.path.join(output_dir, "pen_sketch.mp3"),
        "marker_color": os.path.join(output_dir, "marker_color.mp3"),
    }

    for name, path in sfx_files.items():
        if os.path.exists(path) and not force:
            print(f"  [SKIP] {name}.mp3 already exists")
            continue

        if name == "pen_sketch":
            raw = generate_pen_sketch()
        else:
            raw = generate_marker_color()

        # Convert to pydub AudioSegment and export
        import wave
        import struct

        # Write temp WAV then convert
        temp_wav = path.replace(".mp3", "_temp.wav")
        with wave.open(temp_wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(raw)

        seg = AudioSegment.from_wav(temp_wav)
        seg.export(path, format="mp3", bitrate="192k")
        os.remove(temp_wav)

        print(f"  [GEN] {name}.mp3 -> {path}")

    return sfx_files


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate default synthetic SFX")
    parser.add_argument("--output-dir", "-o", help="Output directory for SFX files")
    parser.add_argument("--force", action="store_true", help="Regenerate even if files exist")
    args = parser.parse_args()

    print("Generating synthetic sound effects...")
    generate_sfx(args.output_dir, args.force)
    print("Done!")
