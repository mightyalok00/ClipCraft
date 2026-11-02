"""Global Configuration for ClipCraft."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Base paths
ROOT_DIR = Path(__file__).resolve().parent


def _load_env_file(env_path: Path) -> None:
    """Load key-value pairs from a .env file into os.environ without requiring external packages."""
    if not env_path.exists():
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_env_file(ROOT_DIR / ".env")

OUTPUT_DIR = Path(os.environ.get("CLIPCRAFT_OUTPUT_DIR", ROOT_DIR / "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOADS_DIR = OUTPUT_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

SHORTS_DIR = OUTPUT_DIR / "shorts"
SHORTS_DIR.mkdir(parents=True, exist_ok=True)

ASSETS_DIR = ROOT_DIR / "assets"
MODELS_DIR = ASSETS_DIR / "models"
FONTS_DIR = ASSETS_DIR / "fonts"
EMOJI_DIR = ASSETS_DIR / "emoji"

CONFIG_FILE = ROOT_DIR / "config.local.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "llm_provider": "gemini",  # gemini, groq, openai, ollama
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
    "groq_api_key": os.environ.get("GROQ_API_KEY", ""),
    "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
    "ollama_base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    "ollama_model": os.environ.get("OLLAMA_MODEL", "llama3.2"),
    "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
    "groq_model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
    "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    "whisper_model": "small",  # tiny, base, small, medium, large-v3
    "whisper_device": "auto",  # auto, cuda, cpu
    "default_aspect_ratio": "9:16",
    "default_captions": "bold_yellow",
    "cut_pauses": True,
    "punch_ins": True,
    "hook_replay": True,
}


_HW_CACHE: dict[str, Any] | None = None


def detect_hardware() -> dict[str, Any]:
    """Detect available compute and hardware acceleration engines (cached)."""
    global _HW_CACHE
    if _HW_CACHE is not None:
        return _HW_CACHE.copy()

    import shutil
    import subprocess

    hw: dict[str, Any] = {
        "cpu_count": os.cpu_count() or 4,
        "has_cuda": False,
        "has_nvenc": False,
        "has_qsv": False,
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
    }

    # Check CUDA availability
    try:
        import torch
        hw["has_cuda"] = torch.cuda.is_available()
    except (ImportError, RuntimeError, OSError):
        try:
            import ctranslate2
            hw["has_cuda"] = ctranslate2.get_cuda_device_count() > 0
        except (ImportError, RuntimeError, OSError):
            hw["has_cuda"] = False

    # Check FFmpeg encoders
    if hw["ffmpeg_available"]:
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        try:
            res = subprocess.run(
                [ffmpeg_bin, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=3,
                check=False,
            )
            stdout = res.stdout or ""
            hw["has_nvenc"] = "h264_nvenc" in stdout
            hw["has_qsv"] = "h264_qsv" in stdout
        except (subprocess.SubprocessError, OSError):
            pass

    _HW_CACHE = hw
    return hw.copy()


def cleanup_old_temp_files(max_age_hours: int = 24) -> int:
    """Clean up orphan audio and temporary video artifacts older than max_age_hours."""
    import time

    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    removed_count = 0

    scan_dirs = [DOWNLOADS_DIR, OUTPUT_DIR]
    for d in scan_dirs:
        if not d.exists():
            continue
        for file in d.iterdir():
            if file.is_file() and file.suffix.lower() in (".wav", ".tmp", ".mp3", ".part"):
                try:
                    if file.stat().st_mtime < cutoff:
                        file.unlink()
                        removed_count += 1
                except OSError:
                    pass

    return removed_count


def load_config() -> dict[str, Any]:
    """Load configuration merged with overrides."""
    conf = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                user_conf = json.load(f)
                conf.update(user_conf)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[config] Failed to load {CONFIG_FILE}: {e}")
    return conf


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    """Save user configuration."""
    conf = load_config()
    conf.update(updates)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(conf, f, indent=2, ensure_ascii=False)
    except (OSError, TypeError) as e:
        print(f"[config] Failed to save {CONFIG_FILE}: {e}")
    return conf
