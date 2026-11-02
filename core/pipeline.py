"""Master Orchestrator Pipeline for ClipCraft."""
from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from config import SHORTS_DIR, load_config

from .compositor import render_clip
from .ingestion import download_video, extract_audio, probe_media
from .packaging import package_clip
from .ranker import rank_highlights
from .signals import compute_loudness_curve, detect_silences, find_audio_peaks, snap_to_silence
from .transcriber import transcribe


def process_video(
    source_url_or_path: str,
    num_clips: int = 3,
    content_type: str = "general",
    layout: str = "facetrack",
    captions: str = "bold_yellow",
    prompt: str = "",
    output_dir: Path | None = None,
    config: dict[str, Any] | None = None,
    progress_callback: Callable[[str, float, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Run end-to-end AI clipping pipeline with live progress updates and cancellation."""
    def notify(stage: str, frac: float, msg: str):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Video processing job cancelled by user.")
        if progress_callback:
            progress_callback(stage, frac, msg)
        print(f"[{stage.upper()}] ({int(frac * 100)}%) {msg}", flush=True)

    conf = config or load_config()
    audio_path: Path | None = None

    try:
        # 1. Ingestion
        notify("download", 0.05, "Acquiring source video...")
        video_path = download_video(source_url_or_path)
        media_info = probe_media(video_path)
        notify("download", 0.15, f"Source ready: {media_info['width']}x{media_info['height']} ({int(media_info['duration'])}s)")

        # 2. Audio extraction
        notify("audio", 0.20, "Extracting high-fidelity speech track...")
        audio_path = extract_audio(video_path)

        # 3. Speech Recognition
        notify("transcribe", 0.30, "Transcribing with faster-whisper (word timestamps)...")
        transcript = transcribe(
            audio_path,
            model_size=conf.get("whisper_model", "small"),
            device=conf.get("whisper_device", "auto"),
        )
        notify("transcribe", 0.50, f"Transcribed {len(transcript.get('words', []))} words across {len(transcript.get('segments', []))} cues.")

        # 4. Audio Hook Signals & Excitement Curves
        notify("signals", 0.55, "Measuring loudness envelope and audio peaks...")
        loudness = compute_loudness_curve(audio_path)
        peaks = find_audio_peaks(loudness, top_n=num_clips * 2)
        silences = detect_silences(loudness, min_silence_sec=0.4, silence_threshold=0.10)
        energy_summary = (
            f"Detected {len(peaks)} high-excitement peaks at: " +
            ", ".join(f"{p[0]:.1f}s" for p in peaks[:5])
        ) if peaks else ""

        # 5. AI Ranking & Virality Scoring (Fused with Audio Peaks)
        notify("ranking", 0.60, f"Analyzing virality with {conf.get('llm_provider', 'LLM').upper()} ({content_type})...")
        highlights = rank_highlights(
            transcript=transcript,
            num_clips=num_clips,
            content_type=content_type,
            prompt_override=prompt,
            energy_summary=energy_summary,
            config=conf,
        )

        if not highlights:
            # Fallback to audio peak spans if LLM produces no output
            notify("ranking", 0.65, "LLM returned no candidates; falling back to audio excitement peaks.")
            for i, (peak_time, _) in enumerate(peaks[:num_clips], 1):
                start = max(0.0, peak_time - 5.0)
                end = min(media_info["duration"], start + 30.0)
                highlights.append({
                    "title": f"Energy Peak {i}",
                    "start_time": round(start, 2),
                    "end_time": round(end, 2),
                    "duration": round(end - start, 2),
                    "score": 85,
                    "hook_score": 90,
                    "first_line": "High energy moment",
                    "hook_sentence": "Check this out!",
                    "virality_reason": "Audible excitement peak",
                })

        # 6. Audio Pause Snapping: Align cuts to natural speech boundaries
        for h in highlights:
            snapped_st = snap_to_silence(h["start_time"], silences, is_start=True, max_shift=1.2)
            snapped_et = snap_to_silence(h["end_time"], silences, is_start=False, max_shift=1.2)
            if snapped_et > snapped_st and (snapped_et - snapped_st) >= 15.0:
                h["start_time"] = round(snapped_st, 2)
                h["end_time"] = round(snapped_et, 2)
                h["duration"] = round(snapped_et - snapped_st, 2)

        # 7. Rendering & Packaging
        rendered_shorts = []
        job_id = int(time.time())
        job_out_dir = output_dir or (SHORTS_DIR / f"job_{job_id}")
        job_out_dir.mkdir(parents=True, exist_ok=True)

        words = transcript.get("words", [])

        for i, h in enumerate(highlights, 1):
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Video processing job cancelled by user.")

            frac = 0.70 + (i / len(highlights)) * 0.28
            notify("rendering", frac, f"Compositing Short #{i}/{len(highlights)}: '{h['title']}'...")

            out_filename = f"short_{i:02d}_{h['title'].lower().replace(' ', '_')[:30]}.mp4"
            out_path = job_out_dir / out_filename

            render_clip(
                source_path=video_path,
                start_time=h["start_time"],
                end_time=h["end_time"],
                output_path=out_path,
                layout=layout,
                words=words,
                caption_preset=captions,
                hook_text=h.get("hook_sentence", ""),
            )

            # Generate SEO packaging
            seo = package_clip(h, content_type=content_type)
            h["seo"] = seo
            h["clip_url"] = str(out_path)
            rendered_shorts.append(h)

        notify("completed", 1.0, f"Successfully created {len(rendered_shorts)} vertical shorts!")

        # Save job manifest
        manifest = {
            "job_id": job_id,
            "source": str(video_path),
            "media_info": media_info,
            "highlights": rendered_shorts,
            "created_at": time.time(),
        }
        (job_out_dir / "job.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    finally:
        # Transient audio cleanup
        if audio_path and audio_path.exists():
            with contextlib.suppress(OSError):
                audio_path.unlink()


