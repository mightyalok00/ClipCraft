
"""High-Performance FFmpeg Hardware-Accelerated Video Compositor."""
from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from typing import Any

from config import FONTS_DIR

from .subtitles import generate_ass_subtitles
from .vision import calculate_crop_window, detect_faces


def detect_hw_encoder() -> tuple[str, list[str]]:
    """Determine best available H.264 video encoder."""
    try:
        proc = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True, check=True)
        out = proc.stdout
        if "h264_nvenc" in out:
            return "h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
        if "h264_qsv" in out:
            return "h264_qsv", ["-c:v", "h264_qsv", "-global_quality", "23"]
    except (subprocess.SubprocessError, OSError):
        pass
    # CPU fallback
    return "libx264", ["-c:v", "libx264", "-preset", "fast", "-crf", "22"]


def render_clip(
    source_path: Path,
    start_time: float,
    end_time: float,
    output_path: Path,
    layout: str = "facetrack",
    words: list[dict[str, Any]] | None = None,
    caption_preset: str = "bold_yellow",
    hook_text: str = "",
    target_res: tuple[int, int] = (1080, 1920),
) -> Path:
    """Render a vertical 9:16 short with smart crop, animated captions, and audio normalization."""
    duration = end_time - start_time
    out_w, out_h = target_res
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Determine video dimensions and sample a frame for face detection
    import cv2
    cap = cv2.VideoCapture(str(source_path))
    cap.set(cv2.CAP_PROP_POS_MSEC, (start_time + 1.0) * 1000.0)
    ret, sample_frame = cap.read()
    cap.release()

    face = None
    if ret and sample_frame is not None:
        src_h, src_w = sample_frame.shape[:2]
        faces = detect_faces(sample_frame)
        if faces:
            # Pick highest confidence or largest face
            faces.sort(key=lambda f: f["w"] * f["h"], reverse=True)
            face = faces[0]
    else:
        src_w, src_h = 1920, 1080

    # 2. Build Subtitles if words are provided and captions enabled
    sub_filter = ""
    ass_path = output_path.with_suffix(".ass")
    if words and caption_preset != "off":
        # Filter words within this clip's time span
        clip_words = [w for w in words if w["start"] >= (start_time - 0.2) and w["end"] <= (end_time + 0.5)]
        if clip_words:
            generate_ass_subtitles(
                words=clip_words,
                output_ass_path=ass_path,
                preset_name=caption_preset,
                hook_text=hook_text,
                clip_offset=start_time,
                width=out_w,
                height=out_h,
            )
            # Escape path for FFmpeg filter
            clean_ass = str(ass_path).replace("\\", "/").replace(":", "\\:")
            clean_fonts = str(FONTS_DIR).replace("\\", "/").replace(":", "\\:")
            sub_filter = f",subtitles='{clean_ass}':fontsdir='{clean_fonts}'"

    # 3. Build Video Filtergraph based on layout
    if layout == "stacked":
        # Webcam top 42% height, gameplay bottom 58%
        cam_h = int(out_h * 0.42)
        game_h = out_h - cam_h
        # Webcam crop around detected face
        crop_box = calculate_crop_window(src_w, src_h, (out_w, cam_h), face=face)
        # Gameplay crop centered
        game_box = calculate_crop_window(src_w, src_h, (out_w, game_h), face=None)

        vf = (
            f"[0:v]split=2[cam_in][game_in];"
            f"[cam_in]crop={crop_box['w']}:{crop_box['h']}:{crop_box['x']}:{crop_box['y']},"
            f"scale={out_w}:{cam_h}:flags=lanczos[cam];"
            f"[game_in]crop={game_box['w']}:{game_box['h']}:{game_box['x']}:{game_box['y']},"
            f"scale={out_w}:{game_h}:flags=lanczos[game];"
            f"[cam][game]vstack=inputs=2[v_stacked];"
            f"[v_stacked]setsar=1{sub_filter}[v]"
        )
    else:
        # Single 9:16 crop window (facetrack or center)
        crop_box = calculate_crop_window(src_w, src_h, (9, 16), face=face if layout == "facetrack" else None)
        vf = (
            f"[0:v]crop={crop_box['w']}:{crop_box['h']}:{crop_box['x']}:{crop_box['y']},"
            f"scale={out_w}:{out_h}:flags=lanczos,setsar=1{sub_filter}[v]"
        )

    # 4. Encoder and Audio Normalization
    _, enc_args = detect_hw_encoder()

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start_time:.3f}",
        "-i", str(source_path),
        "-t", f"{duration:.3f}",
        "-filter_complex", vf,
        "-map", "[v]",
        "-map", "0:a:0?",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        *enc_args,
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    subprocess.run(cmd, check=True)

    # Clean up transient .ass file if created
    if ass_path.exists():
        with contextlib.suppress(OSError):
            ass_path.unlink()

    return output_path
