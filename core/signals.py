"""Audio Signal Processing, Hook Peaks, and Silence Detection."""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import numpy as np


def compute_loudness_curve(wav_path: str | Path, window_ms: int = 100) -> dict[str, Any]:
    """Compute the RMS loudness envelope over a 16kHz mono WAV file."""
    path = str(wav_path)
    with wave.open(path, "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        n_frames = wf.getnframes()
        raw_data = wf.readframes(n_frames)

    samples = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    window_size = int(sample_rate * (window_ms / 1000.0))
    n_windows = len(samples) // window_size

    if n_windows == 0:
        return {"rms": [], "window_sec": window_ms / 1000.0, "duration": 0.0}

    # Reshape and compute RMS per window
    trimmed = samples[: n_windows * window_size]
    windows = trimmed.reshape(n_windows, window_size)
    rms = np.sqrt(np.mean(windows**2, axis=1))

    # Normalize RMS to 0.0 - 1.0 range
    max_val = np.max(rms) if np.max(rms) > 0 else 1.0
    norm_rms = (rms / max_val).tolist()

    return {
        "rms": norm_rms,
        "window_sec": window_ms / 1000.0,
        "duration": n_frames / float(sample_rate),
    }


def find_audio_peaks(loudness_data: dict[str, Any], top_n: int = 10) -> list[tuple[float, float]]:
    """Identify the loudest audio peaks (excitement, screams, laughter)."""
    rms = np.array(loudness_data.get("rms", []))
    if len(rms) == 0:
        return []

    win_sec = loudness_data["window_sec"]
    # Smooth with simple moving average
    kernel = np.ones(5) / 5.0
    smoothed = np.convolve(rms, kernel, mode="same")

    # Pick local maxima above threshold
    threshold = np.mean(smoothed) + 1.2 * np.std(smoothed)
    peaks = []
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] > smoothed[i - 1] and smoothed[i] > smoothed[i + 1] and smoothed[i] >= threshold:
            timestamp = round(i * win_sec, 2)
            score = round(float(smoothed[i]), 3)
            peaks.append((timestamp, score))

    peaks.sort(key=lambda p: p[1], reverse=True)
    return peaks[:top_n]


def detect_silences(
    loudness_data: dict[str, Any],
    min_silence_sec: float = 0.55,
    silence_threshold: float = 0.08,
) -> list[tuple[float, float]]:
    """Locate quiet dead-air silence spans suitable for jump-cutting."""
    rms = np.array(loudness_data.get("rms", []))
    if len(rms) == 0:
        return []

    win_sec = loudness_data["window_sec"]
    is_quiet = rms < silence_threshold

    silences: list[tuple[float, float]] = []
    in_silence = False
    start_idx = 0

    for i, quiet in enumerate(is_quiet):
        if quiet and not in_silence:
            in_silence = True
            start_idx = i
        elif not quiet and in_silence:
            in_silence = False
            duration = (i - start_idx) * win_sec
            if duration >= min_silence_sec:
                silences.append((round(start_idx * win_sec, 2), round(i * win_sec, 2)))

    return silences


def snap_to_silence(
    time_sec: float,
    silences: list[tuple[float, float]],
    is_start: bool = True,
    max_shift: float = 1.0,
) -> float:
    """Snap a timestamp to the nearest silence midpoint within max_shift."""
    best_time = time_sec
    min_dist = max_shift + 1e-5

    for s_start, s_end in silences:
        midpoint = (s_start + s_end) / 2.0
        dist = abs(time_sec - midpoint)
        if dist <= max_shift and dist < min_dist:
            min_dist = dist
            best_time = round(midpoint, 2)

    return best_time


# Aliases for compatibility
compute_loudness_envelope = compute_loudness_curve
find_silence_ranges = detect_silences

