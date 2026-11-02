"""High-Production Animated Karaoke Subtitles (.ass for libass)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

from config import FONTS_DIR


@dataclass
class WordToken:
    word: str
    start: float
    end: float

    def __getitem__(self, item):
        return getattr(self, item)


# Subtitle Presets
# Note: In ASS colors are &HAABBGGRR& (BGR order)
PRESETS = {
    "bold_yellow": {
        "name": "Bold Yellow",
        "font": "Montserrat Black",
        "file": "Montserrat-Black.ttf",
        "fontsize": 38,
        "primary": "&H00FFFFFF&",    # White
        "active": "&H004DE1FF&",     # Bright Gold/Yellow in BGR
        "outline_col": "&H00000000&",# Black
        "outline": 3.5,
        "shadow": 1.5,
        "uppercase": True,
    },
    "cyber_green": {
        "name": "Cyber Neon",
        "font": "Anton",
        "file": "Anton-Regular.ttf",
        "fontsize": 42,
        "primary": "&H00FFFFFF&",    # White
        "active": "&H0066FF00&",     # Neon Green in BGR
        "outline_col": "&H00101010&",
        "outline": 4.0,
        "shadow": 2.0,
        "uppercase": True,
    },
    "clean_minimal": {
        "name": "Clean Box",
        "font": "Poppins Black",
        "file": "Poppins-Black.ttf",
        "fontsize": 32,
        "primary": "&H00F0F0F0&",
        "active": "&H0000FFFF&",     # Cyan
        "outline_col": "&H00000000&",
        "outline": 2.0,
        "shadow": 0.0,
        "uppercase": False,
    },
}


def generate_ass_subtitles(
    words: List[Union[Dict[str, Any], WordToken]],
    output_ass_path: Path,
    preset_name: str = "bold_yellow",
    style: Optional[str] = None,
    hook_text: str = "",
    clip_offset: float = 0.0,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    """Generate an animated .ass subtitle file with word-by-word active highlights."""
    chosen_preset = style or preset_name
    preset = PRESETS.get(chosen_preset, PRESETS["bold_yellow"])

    # Group words into 3-5 word chunks
    chunks = []
    chunk_size = 4
    for i in range(0, len(words), chunk_size):
        group = words[i: i + chunk_size]
        if group:
            chunks.append(group)

    events = []

    # If hook text is provided, show it at the top for first 2.5 seconds
    if hook_text:
        hook_clean = hook_text.strip().replace("\n", " ")
        if preset["uppercase"]:
            hook_clean = hook_clean.upper()
        # Top-center alignment (\an8)
        events.append(
            f"Dialogue: 1,0:00:00.00,0:00:02.80,Hook,,0,0,0,,{{\\an8\\pos({width // 2},140)}}"
            f"{hook_clean}"
        )

    # Spoken words in lower middle (\an5 / center-aligned)
    y_pos = int(height * 0.72)

    for group in chunks:
        g_start = max(0.0, group[0]["start"] - clip_offset)
        g_end = max(g_start + 0.3, group[-1]["end"] - clip_offset)

        # For each word in the group, build animated karaoke line
        # When word w is active: color is preset["active"], else preset["primary"]
        for active_idx, target_word in enumerate(group):
            w_start = max(0.0, target_word["start"] - clip_offset)
            w_end = max(w_start + 0.1, target_word["end"] - clip_offset)

            # Build line text
            line_parts = []
            for idx, w in enumerate(group):
                word_txt = w["word"].strip()
                if preset["uppercase"]:
                    word_txt = word_txt.upper()
                if idx == active_idx:
                    # Highlighted active word
                    line_parts.append(f"{{\\c{preset['active']}}}{word_txt}{{\\c{preset['primary']}}}")
                else:
                    line_parts.append(word_txt)

            line_str = " ".join(line_parts)
            s_str = _format_ass_time(w_start)
            e_str = _format_ass_time(w_end)

            events.append(
                f"Dialogue: 0,{s_str},{e_str},Default,,0,0,0,,{{\\an5\\pos({width // 2},{y_pos})}}{line_str}"
            )

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{preset['font']},{preset['fontsize'] * 2},{preset['primary']},{preset['active']},{preset['outline_col']},&H80000000,-1,0,0,0,100,100,0,0,1,{preset['outline'] * 2},{preset['shadow'] * 2},5,20,20,20,1
Style: Hook,{preset['font']},{int(preset['fontsize'] * 1.5)},&H00FFFFFF&,&H00FFFFFF&,&H00000000&,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,8,40,40,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(events) + "\n"

    output_ass_path.parent.mkdir(parents=True, exist_ok=True)
    output_ass_path.write_text(header, encoding="utf-8")
    return output_ass_path


def _format_ass_time(seconds: float) -> str:
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# Public alias for ASS timestamp formatting
to_ass_time = _format_ass_time

