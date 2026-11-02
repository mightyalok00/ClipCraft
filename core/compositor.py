
"""High-Performance FFmpeg Hardware-Accelerated Video Compositor."""
from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from typing import Any

from config import FONTS_DIR
from core.logger import logger
from core.security import resolve_executable

from .subtitles import generate_ass_subtitles
from .vision import calculate_crop_window, detect_faces, sample_video_frame


def detect_hw_encoder() -> tuple[str, list[str]]:
    """Determine best available H.264 video encoder."""
    ffmpeg_bin = resolve_executable("ffmpeg")
    try:
        proc = subprocess.run([ffmpeg_bin, "-encoders"], capture_output=True, text=True, check=True, timeout=10)
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
    """Render a vertical 9:16 short with multi-frame face tracking, blur padding, and GPU/CPU fallback."""
    duration = end_time - start_time
    out_w, out_h = target_res
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Multi-Frame Face Tracking: sample 3 timestamps across the interval for rock-solid stability
    sample_timestamps = [
        start_time + 0.5,
        start_time + duration * 0.3,
        start_time + duration * 0.6,
    ]
    detected_faces = []
    src_w, src_h = 1920, 1080

    for ts in sample_timestamps:
        frame = sample_video_frame(source_path, ts)
        if frame is not None:
            src_h, src_w = frame.shape[:2]
            f_list = detect_faces(frame)
            if f_list:
                f_list.sort(key=lambda f: f["w"] * f["h"], reverse=True)
                detected_faces.append(f_list[0])

    face = None
    if detected_faces:
        # Compute smoothed face center and dimensions across samples
        avg_cx = sum(f["cx"] for f in detected_faces) / len(detected_faces)
        avg_cy = sum(f["cy"] for f in detected_faces) / len(detected_faces)
        avg_w = sum(f["w"] for f in detected_faces) / len(detected_faces)
        avg_h = sum(f["h"] for f in detected_faces) / len(detected_faces)
        face = {
            "cx": avg_cx,
            "cy": avg_cy,
            "w": avg_w,
            "h": avg_h,
            "x": avg_cx - avg_w / 2.0,
            "y": avg_cy - avg_h / 2.0,
            "conf": sum(f.get("conf", 0.8) for f in detected_faces) / len(detected_faces),
        }

    # 2. Build Subtitles if words are provided and captions enabled
    sub_filter = ""
    ass_path = output_path.with_suffix(".ass")
    if words and caption_preset != "off":
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
            clean_ass = str(ass_path).replace("\\", "/").replace(":", "\\:")
            clean_fonts = str(FONTS_DIR).replace("\\", "/").replace(":", "\\:")
            sub_filter = f",subtitles='{clean_ass}':fontsdir='{clean_fonts}'"

    # 3. Build Video Filtergraph based on layout
    if layout == "stacked":
        # Webcam top 42% height, gameplay bottom 58%
        cam_h = int(out_h * 0.42)
        game_h = out_h - cam_h
        crop_box = calculate_crop_window(src_w, src_h, (out_w, cam_h), face=face)
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
    elif layout == "blur_padding":
        # Aesthetic blurred background with original video centered (perfect for 16:9 gameplay/tutorials)
        vf = (
            f"[0:v]split=2[bg_in][fg_in];"
            f"[bg_in]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},boxblur=25:5[bg_blur];"
            f"[fg_in]scale={out_w}:-2:force_original_aspect_ratio=decrease[fg_scaled];"
            f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[v_padded];"
            f"[v_padded]setsar=1{sub_filter}[v]"
        )
    else:
        # Single 9:16 crop window (facetrack or center)
        crop_box = calculate_crop_window(src_w, src_h, (9, 16), face=face if layout == "facetrack" else None)
        vf = (
            f"[0:v]crop={crop_box['w']}:{crop_box['h']}:{crop_box['x']}:{crop_box['y']},"
            f"scale={out_w}:{out_h}:flags=lanczos,setsar=1{sub_filter}[v]"
        )

    # 4. Encoder Execution with Automatic CPU Fallback
    _, enc_args = detect_hw_encoder()

    def _build_cmd(encoder_args: list[str]) -> list[str]:
        return [
            resolve_executable("ffmpeg"), "-y", "-loglevel", "error",
            "-ss", f"{start_time:.3f}",
            "-i", str(source_path),
            "-t", f"{duration:.3f}",
            "-filter_complex", vf,
            "-map", "[v]",
            "-map", "0:a:0?",
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            *encoder_args,
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path),
        ]

    cmd = _build_cmd(enc_args)
    try:
        subprocess.run(cmd, check=True, timeout=600)
    except subprocess.CalledProcessError as e:
        # If hardware encoder failed, fall back to libx264 CPU encoding
        cpu_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "22"]
        if enc_args != cpu_args:
            logger.warning(f"Hardware encoder failed ({e}). Falling back to libx264 CPU render...")
            fallback_cmd = _build_cmd(cpu_args)
            subprocess.run(fallback_cmd, check=True, timeout=600)
        else:
            raise

    # Clean up transient .ass file if created
    if ass_path.exists():
        with contextlib.suppress(OSError):
            ass_path.unlink()

    return output_path
