"""Media Ingestion, Probing, and Audio Extraction."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from config import DOWNLOADS_DIR


def probe_media(file_path: str | Path) -> dict[str, Any]:
    """Inspect video file metadata using ffprobe."""
    path = str(file_path)
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=width,height,r_frame_rate,codec_name,codec_type",
        "-of", "json",
        path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(proc.stdout)
    except Exception as e:
        raise RuntimeError(f"Failed to probe media '{path}': {e}") from e

    v_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})

    fps = 30.0
    r_frame_rate = v_stream.get("r_frame_rate", "30/1")
    if "/" in r_frame_rate:
        num, den = r_frame_rate.split("/")
        try:
            fps = float(num) / float(den)
        except ZeroDivisionError:
            fps = 30.0

    return {
        "width": int(v_stream.get("width") or 1920),
        "height": int(v_stream.get("height") or 1080),
        "duration": float(fmt.get("duration") or 0.0),
        "size_bytes": int(fmt.get("size") or 0),
        "fps": round(fps, 2),
        "video_codec": v_stream.get("codec_name", "unknown"),
        "audio_codec": a_stream.get("codec_name", "none"),
    }


def download_video(source_url_or_path: str, max_height: int = 1080) -> Path:
    """Download video from YouTube/Web or return existing local path."""
    source = source_url_or_path.strip().strip('"').strip("'")

    # Check if it's already a local file path
    local_p = Path(source)
    if local_p.exists() and local_p.is_file():
        return local_p.resolve()

    # If it's a URL, download with yt-dlp
    import yt_dlp  # type: ignore

    out_tmpl = str(DOWNLOADS_DIR / "%(id)s.%(ext)s")
    ydl_opts: Any = {
        "format": f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best",
        "outtmpl": out_tmpl,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(source, download=True)
        target_path = ydl.prepare_filename(info)
        # Ensure mp4 extension if merged
        stem = Path(target_path).stem
        final_mp4 = DOWNLOADS_DIR / f"{stem}.mp4"
        if final_mp4.exists():
            return final_mp4
        if Path(target_path).exists():
            return Path(target_path)

    raise FileNotFoundError(f"Could not download or find media for '{source}'")


def extract_audio(video_path: Path, output_audio: Path | None = None) -> Path:
    """Extract a 16kHz mono 16-bit WAV audio track for transcription and signal analysis."""
    if output_audio is None:
        output_audio = video_path.with_suffix(".16k.wav")

    if output_audio.exists() and output_audio.stat().st_size > 0:
        return output_audio

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_audio),
    ]
    subprocess.run(cmd, check=True)
    return output_audio

