"""ClipCraft — Universal AI Video Clipper & Virality Engine CLI.

Usage:
    python main.py clip <source> [options]
    python main.py web [--host 127.0.0.1] [--port 8000]
    python main.py config [--show] [--set KEY=VALUE]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from config import (  # noqa: E402
    detect_hardware,
    load_config,
    save_config,
)
from core.pipeline import process_video  # noqa: E402


def print_banner():
    banner = (
        r"   _____ _ _         _____            __ _   " + "\n"
        r"  / ____| (_)       / ____|          / _| |  " + "\n"
        r" | |    | |_ _ __  | |     _ __ __ _| |_| |_ " + "\n"
        r" | |    | | | '_ \ | |    | '__/ _` |  _| __|" + "\n"
        r" | |____| | | |_) || |____| | | (_| | | | |_ " + "\n"
        r"  \_____|_|_| .__/  \_____|_|  \__,_|_|  \__|" + "\n"
        r"            | |                              " + "\n"
        r"            |_|   Universal AI Shorts Engine ⚡"
    )
    print(banner)


def cli_progress_callback(stage: str, frac: float, msg: str):
    pct = int(frac * 100)
    bar_length = 24
    filled = int(bar_length * frac)
    bar = "█" * filled + "░" * (bar_length - filled)
    icons = {
        "starting": "⏳",
        "ingestion": "📥",
        "audio_extract": "🔊",
        "transcription": "🗣️ ",
        "signals": "📊",
        "ranking": "🤖",
        "rendering": "🎬",
        "packaging": "📦",
        "completed": "✅",
        "error": "❌",
    }
    icon = icons.get(stage, "⚡")
    print(f"\r{icon} [{bar}] {pct:3d}% | {msg[:55]:<55}", end="", flush=True)
    if frac >= 1.0 or stage in ("completed", "error"):
        print()


def handle_clip(args):
    print_banner()
    source = args.source
    if not source:
        print("❌ Error: source URL or local file path is required.")
        sys.exit(1)

    print(f"🎯 Target Source:   {source}")
    print(f"🎬 Content Type:    {args.category.upper()}")
    print(f"📐 Layout Mode:     {args.layout}")
    print(f"🎨 Caption Style:   {args.captions}")
    print(f"🔢 Clip Count:      {args.num_clips}")
    if args.prompt:
        print(f"💡 Custom Focus:    \"{args.prompt}\"")
    print("-" * 65)

    start_time = time.time()
    try:
        manifest = process_video(
            source_url_or_path=source,
            num_clips=args.num_clips,
            content_type=args.category,
            layout=args.layout,
            captions=args.captions,
            prompt=args.prompt or "",
            output_dir=Path(args.out_dir) if args.out_dir else None,
            progress_callback=cli_progress_callback,
        )
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    elapsed = time.time() - start_time
    clips = manifest.get("clips", [])
    print("\n" + "=" * 65)
    print(f"🎉 Processed {len(clips)} clip(s) successfully in {elapsed:.1f}s!")
    print("=" * 65)

    for i, clip in enumerate(clips, start=1):
        score = clip.get("virality_score", 0)
        title = clip.get("title", f"Clip #{i}")
        file_path = clip.get("file_path", "")
        duration = clip.get("duration", 0)
        reels_hook = clip.get("reels_caption", "")[:70]
        print(f"\n[{i}] ⭐ Virality Score: {score}/100 | Duration: {duration:.1f}s")
        print(f"    🏷️  Title:      {title}")
        print(f"    🎣 Hook:       {reels_hook}...")
        print(f"    📁 Rendered:   {file_path}")

    job_dir = Path(manifest.get("job_dir", ""))
    print(f"\n📂 All deliverables saved to:\n   {job_dir}")

    if args.open and job_dir.exists() and sys.platform == "win32":
        os.startfile(str(job_dir))


def handle_web(args):
    print_banner()
    import uvicorn
    cfg = load_config()
    print(f"🚀 Starting ClipCraft Web Dashboard on http://{args.host}:{args.port}")
    print(f"⚙️  Active LLM Provider: {cfg.get('llm_provider')}")
    print(f"🎙️  Whisper Model:      {cfg.get('whisper_model')} ({cfg.get('whisper_device')})")
    print("💡 Press Ctrl+C to terminate.")
    print("-" * 65)
    uvicorn.run("web.server:app", host=args.host, port=args.port, reload=args.reload)


def handle_config(args):
    cfg = load_config()
    hw = detect_hardware()

    if args.set:
        updates = {}
        for item in args.set:
            if "=" in item:
                k, v = item.split("=", 1)
                updates[k.strip()] = v.strip()
        if updates:
            saved = save_config(updates)
            print(f"✅ Updated configuration keys: {list(updates.keys())}")
            cfg = saved

    print("\n📋 Current ClipCraft Configuration:")
    print("-" * 45)
    for k, v in cfg.items():
        if "api_key" in k and v:
            censored = v[:4] + "..." + v[-4:] if len(v) > 8 else "****"
            print(f"  {k:<20}: {censored}")
        else:
            print(f"  {k:<20}: {v}")

    print("\n🖥️  Detected Hardware:")
    print("-" * 45)
    for k, v in hw.items():
        print(f"  {k:<20}: {v}")
    print()


def main():
    parser = argparse.ArgumentParser(
        prog="clipcraft",
        description="ClipCraft: Universal AI Video Clipper & Virality Engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # Command: clip
    p_clip = subparsers.add_parser("clip", help="Generate viral shorts from a video source")
    p_clip.add_argument("source", nargs="?", help="YouTube/Twitch URL or local video file path")
    p_clip.add_argument("-n", "--num-clips", type=int, default=3, help="Number of clips to generate (default: 3)")
    p_clip.add_argument(
        "-c", "--category",
        choices=["general", "gaming", "podcast", "education", "vlog"],
        default="general",
        help="Content archetype to tune virality criteria (default: general)",
    )
    p_clip.add_argument(
        "-l", "--layout",
        choices=["facetrack", "stacked", "blur_padding"],
        default="facetrack",
        help="Video layout: facetrack (active speaker crop), stacked (facecam + content), or blur_padding (default: facetrack)",
    )
    p_clip.add_argument(
        "-s", "--captions",
        choices=["bold_yellow", "cyber_green", "clean_minimal"],
        default="bold_yellow",
        help="Subtitle styling preset (default: bold_yellow)",
    )
    p_clip.add_argument("-p", "--prompt", default="", help="Custom prompt to guide clip ranking")
    p_clip.add_argument("-o", "--out-dir", default=None, help="Custom output directory")
    p_clip.add_argument("--open", action="store_true", help="Open output directory in file explorer upon completion")

    # Command: web
    p_web = subparsers.add_parser("web", help="Launch the web dashboard")
    p_web.add_argument("--host", default="127.0.0.1", help="Host IP (default: 127.0.0.1)")
    p_web.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    p_web.add_argument("--reload", action="store_true", help="Enable live code reload")

    # Command: config
    p_config = subparsers.add_parser("config", help="View or modify settings")
    p_config.add_argument("--show", action="store_true", help="Show current config and hardware status")
    p_config.add_argument("--set", nargs="+", help="Set configuration values like llm_provider=groq")

    args = parser.parse_args()

    if args.command == "clip":
        handle_clip(args)
    elif args.command in ("web", "server"):
        handle_web(args)
    elif args.command == "config":
        handle_config(args)
    else:
        # Default behavior: if no subcommand, launch web dashboard or show help
        if len(sys.argv) == 1:
            print_banner()
            parser.print_help()
            print("\n💡 Quick Start:")
            print("   python main.py web                   # Start web dashboard")
            print("   python main.py clip <URL_OR_FILE>    # Generate clips via CLI")
            print("   python main.py config --show         # Check hardware & API setup\n")
        else:
            parser.print_help()


if __name__ == "__main__":
    main()

