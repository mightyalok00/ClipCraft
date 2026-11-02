"""Speech Recognition with Word-Level Timestamps and Multi-Tier Caching."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_model_cache = {}


def detect_device() -> str:
    """Check if CUDA is available for ctranslate2."""
    try:
        import ctranslate2  # type: ignore
        if "cuda" in ctranslate2.get_supported_devices():
            return "cuda"
    except (ImportError, AttributeError, RuntimeError):
        pass
    return "cpu"


def get_whisper_model(model_size: str = "small", device: str = "auto"):
    """Load or retrieve cached faster-whisper model."""
    if device == "auto":
        device = detect_device()

    key = (model_size, device)
    if key in _model_cache:
        return _model_cache[key], device

    from faster_whisper import WhisperModel  # type: ignore

    compute_type = "float16" if device == "cuda" else "int8"
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        if device == "cuda":
            print(f"[transcriber] CUDA load failed ({e}), falling back to CPU")
            device = "cpu"
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
        else:
            raise

    _model_cache[(model_size, device)] = model
    return model, device


def transcribe(
    audio_path: str | Path,
    model_size: str = "small",
    device: str = "auto",
    language: str | None = "en",
) -> dict[str, Any]:
    """Transcribe audio with segment and word timestamps. Caches to .words.json and .srt."""
    audio_p = Path(audio_path)
    cache_json = audio_p.with_suffix(".words.json")
    cache_srt = audio_p.with_suffix(".srt")

    # Load cache if available
    if cache_json.exists():
        try:
            cached_data = json.loads(cache_json.read_text(encoding="utf-8"))
            if isinstance(cached_data, dict) and "segments" in cached_data:
                return cached_data
        except (json.JSONDecodeError, OSError):
            pass

    model, actual_device = get_whisper_model(model_size, device)
    lang = language.strip().lower() if language else None
    if lang == "auto":
        lang = None

    print(f"[transcriber] Transcribing on {actual_device.upper()} (model={model_size}, lang={lang or 'auto'})...")
    segments_gen, info = model.transcribe(
        str(audio_p),
        language=lang,
        beam_size=5,
        word_timestamps=True,
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    segments_out = []
    all_words = []
    srt_lines = []

    for idx, seg in enumerate(segments_gen, 1):
        # Suppress common Whisper hallucination artifacts during silence
        if getattr(seg, "no_speech_prob", 0.0) > 0.8 or not str(seg.text or "").strip():
            continue

        seg_words = []
        for w in getattr(seg, "words", None) or []:
            text = str(w.word or "").strip()
            if not text:
                continue
            prob = float(getattr(w, "probability", 1.0) or 0.0)
            if prob < 0.15:  # Filter out low-confidence hallucinations
                continue

            word_obj = {
                "word": text,
                "start": round(float(w.start), 3),
                "end": round(float(w.end), 3),
                "p": round(prob, 3),
            }
            seg_words.append(word_obj)
            all_words.append(word_obj)

        segment_obj = {
            "id": idx,
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": str(seg.text or "").strip(),
            "words": seg_words,
        }
        segments_out.append(segment_obj)

        # Build SRT line
        s_time = _format_srt_time(float(seg.start))
        e_time = _format_srt_time(float(seg.end))
        srt_lines.append(f"{idx}\n{s_time} --> {e_time}\n{segment_obj['text']}\n")

    result = {
        "language": info.language,
        "language_probability": round(float(info.language_probability), 3),
        "duration": round(float(info.duration), 3),
        "segments": segments_out,
        "words": all_words,
    }

    # Save caches
    try:
        cache_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        cache_srt.write_text("\n".join(srt_lines), encoding="utf-8")
    except OSError as e:
        print(f"[transcriber] Failed writing cache: {e}")

    return result


def _format_srt_time(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

