"""Master Orchestrator Pipeline for ClipCraft."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

from config import SHORTS_DIR, load_config
from .ingestion import download_video, extract_audio, probe_media
from .transcriber import transcribe
from .signals import compute_loudness_curve, find_audio_peaks
from .ranker import rank_highlights
from .compositor import render_clip
from .packaging import package_clip


def process_video(
    source_url_or_path: str,
    num_clips: int = 3,
    content_type: str = "general",
    layout: str = "facetrack",
    captions: str = "bold_yellow",
    prompt: str = "",
    config: Optional[Dict[str, Any]] = None,
    progress_callback: Optional[Callable[[str, float, str], None]] = None,
) -> Dict[str, Any]:
    """Run end-to-end AI clipping pipeline with live progress updates."""
    def notify(stage: str, frac: float, msg: str):
        if progress_callback:
            progress_callback(stage, frac, msg)
        print(f"[{stage.upper()}] ({int(frac * 100)}%) {msg}", flush=True)

    conf = config or load_config()

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

    # 4. Audio Hook Signals
    notify("signals", 0.55, "Measuring loudness envelope and audio peaks...")
    loudness = compute_loudness_curve(audio_path)
    peaks = find_audio_peaks(loudness, top_n=num_clips * 2)

    # 5. AI Ranking & Virality Scoring
    notify("ranking", 0.60, f"Analyzing virality with {conf.get('llm_provider', 'LLM').upper()} ({content_type})...")
    highlights = rank_highlights(
        transcript=transcript,
        num_clips=num_clips,
        content_type=content_type,
        prompt_override=prompt,
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

    # 6. Rendering & Packaging
    rendered_shorts = []
    job_id = int(time.time())
    job_out_dir = SHORTS_DIR / f"job_{job_id}"
    job_out_dir.mkdir(parents=True, exist_ok=True)

    words = transcript.get("words", [])

    for i, h in enumerate(highlights, 1):
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
