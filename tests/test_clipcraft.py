"""ClipCraft Automated Test Suite."""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

# Add project root to path
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import load_config, save_config, detect_hardware
from core.signals import compute_loudness_envelope, find_silence_ranges, snap_to_silence
from core.subtitles import generate_ass_subtitles, to_ass_time, WordToken
from core.vision import calculate_crop_box, calculate_stacked_crops
from core.ranker import _extract_json, build_prompt_for_category
from core.packaging import package_clip_deliverables


class TestConfig(unittest.TestCase):
    def test_hardware_detection(self):
        hw = detect_hardware()
        self.assertIn("has_cuda", hw)
        self.assertIn("has_nvenc", hw)
        self.assertIn("cpu_count", hw)
        self.assertIsInstance(hw["cpu_count"], int)

    def test_load_config_defaults(self):
        cfg = load_config()
        self.assertIn("llm_provider", cfg)
        self.assertIn("whisper_model", cfg)
        self.assertIn("whisper_device", cfg)


class TestSignals(unittest.TestCase):
    def test_silence_snapping(self):
        # Silence from 10.0 to 11.0, 20.0 to 21.0
        silences = [(10.0, 11.0), (20.0, 21.0)]
        
        # Test start snap near 10.3 -> snaps to 10.5
        snapped_start = snap_to_silence(10.3, silences, is_start=True, max_shift=1.0)
        self.assertAlmostEqual(snapped_start, 10.5, places=2)

        # Test end snap near 20.8 -> snaps to 20.5
        snapped_end = snap_to_silence(20.8, silences, is_start=False, max_shift=1.0)
        self.assertAlmostEqual(snapped_end, 20.5, places=2)

        # Test no silence nearby -> returns original
        unchanged = snap_to_silence(5.0, silences, is_start=True, max_shift=0.5)
        self.assertEqual(unchanged, 5.0)


class TestSubtitles(unittest.TestCase):
    def test_to_ass_time(self):
        self.assertEqual(to_ass_time(0.0), "0:00:00.00")
        self.assertEqual(to_ass_time(65.432), "0:01:05.43")
        self.assertEqual(to_ass_time(3661.12), "1:01:01.12")

    def test_generate_ass_bold_yellow(self):
        words = [
            WordToken(word="This", start=0.0, end=0.3),
            WordToken(word="is", start=0.35, end=0.6),
            WordToken(word="amazing", start=0.65, end=1.2),
        ]
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w", encoding="utf-8") as tf:
            temp_path = Path(tf.name)

        try:
            generate_ass_subtitles(words, temp_path, style="bold_yellow")
            content = temp_path.read_text(encoding="utf-8")
            self.assertIn("[Script Info]", content)
            self.assertIn("[V4+ Styles]", content)
            self.assertIn("[Events]", content)
            self.assertIn("Dialogue:", content)
            self.assertIn("AMAZING", content.upper())
            self.assertIn(r"\c&H", content)  # Color highlight tags
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_generate_ass_cyber_green(self):
        words = [
            WordToken(word="Welcome", start=0.0, end=0.5),
            WordToken(word="to", start=0.5, end=0.8),
            WordToken(word="ClipCraft", start=0.8, end=1.5),
        ]
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w", encoding="utf-8") as tf:
            temp_path = Path(tf.name)

        try:
            generate_ass_subtitles(words, temp_path, style="cyber_green")
            content = temp_path.read_text(encoding="utf-8")
            self.assertIn("CLIPCRAFT", content.upper())
            self.assertIn("Anton", content)
        finally:
            if temp_path.exists():
                temp_path.unlink()


class TestVisionCrops(unittest.TestCase):
    def test_calculate_crop_box_center(self):
        # 1920x1080 video -> 9:16 target -> width = 1080 * 9 / 16 = 607.5 -> round 608
        # Center at (960, 540)
        x, y, w, h = calculate_crop_box(
            frame_width=1920,
            frame_height=1080,
            face_center_x=960,
            face_center_y=540,
            target_aspect=9/16,
        )
        self.assertEqual(h, 1080)
        self.assertEqual(w, 608)
        self.assertAlmostEqual(x + w / 2, 960, delta=2)
        self.assertEqual(y, 0)

    def test_calculate_crop_box_clamping_left(self):
        # Face all the way on the left (x=50) -> cannot go negative
        x, y, w, h = calculate_crop_box(
            frame_width=1920,
            frame_height=1080,
            face_center_x=50,
            face_center_y=540,
            target_aspect=9/16,
        )
        self.assertEqual(x, 0)
        self.assertEqual(w, 608)

    def test_calculate_crop_box_clamping_right(self):
        # Face all the way on the right (x=1900) -> cannot exceed 1920 - 608
        x, y, w, h = calculate_crop_box(
            frame_width=1920,
            frame_height=1080,
            face_center_x=1900,
            face_center_y=540,
            target_aspect=9/16,
        )
        self.assertEqual(x, 1920 - 608)
        self.assertEqual(w, 608)

    def test_calculate_stacked_crops(self):
        # Split layout: top facecam, bottom gameplay
        top_crop, bottom_crop = calculate_stacked_crops(1920, 1080, face_bbox=(200, 100, 300, 300))
        self.assertIn("x", top_crop)
        self.assertIn("y", top_crop)
        self.assertIn("x", bottom_crop)
        self.assertIn("y", bottom_crop)
        self.assertGreater(top_crop["w"], 0)
        self.assertGreater(bottom_crop["w"], 0)


class TestRanker(unittest.TestCase):
    def test_extract_json_markdown(self):
        raw = """Here is your response:
```json
[
  {"start": 12.0, "end": 45.0, "title": "Insane Gaming Play", "virality_score": 95, "hook": "You won't believe this"}
]
```
Hope you like it!"""
        parsed = _extract_json(raw)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "Insane Gaming Play")
        self.assertEqual(parsed[0]["virality_score"], 95)

    def test_extract_json_raw(self):
        raw = '[{"start": 5.0, "end": 20.0, "title": "Raw Test", "virality_score": 88}]'
        parsed = _extract_json(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "Raw Test")

    def test_prompt_generation_categories(self):
        for cat in ["gaming", "podcast", "education", "vlog", "general"]:
            prompt = build_prompt_for_category(
                category=cat,
                transcript_text="Test transcript",
                num_clips=2,
                energy_summary="High energy at 30s",
                custom_prompt="focus on excitement",
            )
            self.assertIn("focus on excitement", prompt)
            self.assertIn("Test transcript", prompt)
            self.assertIn("High energy at 30s", prompt)


class TestPackaging(unittest.TestCase):
    def test_package_clip_deliverables(self):
        clip = {
            "title": "Secret Python Hack",
            "hook": "Stop writing slow loops!",
            "virality_score": 92,
            "category": "education",
        }
        packaged = package_clip_deliverables(clip)
        self.assertIn("youtube", packaged)
        self.assertIn("reels", packaged)
        self.assertIn("tiktok", packaged)
        
        # YouTube checks
        self.assertIn("#Shorts", packaged["youtube"]["title"])
        self.assertIn("#education", packaged["youtube"]["hashtags"])

        # Reels checks
        self.assertIn("Stop writing slow loops!", packaged["reels"]["caption"])
        self.assertIn("virality_score", packaged)


if __name__ == "__main__":
    unittest.main()
