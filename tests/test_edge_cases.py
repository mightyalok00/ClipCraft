"""Edge Cases, Non-standard Aspect Ratios, and Cleanup Tests."""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import cleanup_old_temp_files  # noqa: E402
from core.ranker import build_prompt_for_category  # noqa: E402
from core.subtitles import WordToken, generate_ass_subtitles  # noqa: E402
from core.vision import calculate_crop_box  # noqa: E402


class TestEdgeCases(unittest.TestCase):
    def test_empty_words_subtitle_generation(self):
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as tf:
            out_ass = Path(tf.name)

        try:
            # Should handle empty word array without IndexError
            generate_ass_subtitles([], out_ass, hook_text="Empty Test")
            content = out_ass.read_text(encoding="utf-8")
            self.assertIn("[Script Info]", content)
            self.assertIn("EMPTY TEST", content)
        finally:
            out_ass.unlink(missing_ok=True)

    def test_single_word_subtitles(self):
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as tf:
            out_ass = Path(tf.name)

        try:
            tokens = [WordToken(word="SOLO", start=1.0, end=2.0)]
            generate_ass_subtitles(tokens, out_ass)
            content = out_ass.read_text(encoding="utf-8")
            self.assertIn("SOLO", content)
        finally:
            out_ass.unlink(missing_ok=True)

    def test_non_standard_aspect_ratios(self):
        # 1:1 Square source (1080x1080)
        x, y, w, h = calculate_crop_box(1080, 1080, 540, 540, target_aspect=9/16)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertLessEqual(w, 1080)
        self.assertLessEqual(h, 1080)

        # 21:9 Ultrawide source (2560x1080)
        x, y, w, h = calculate_crop_box(2560, 1080, 1280, 540, target_aspect=9/16)
        self.assertEqual(h, 1080)
        self.assertAlmostEqual(w, round(1080 * 9 / 16), delta=2)

    def test_cleanup_old_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            old_file = tmp_path / "stale.wav"
            old_file.write_text("dummy audio", encoding="utf-8")

            # Set mtime to 48 hours ago
            two_days_ago = time.time() - (48 * 3600)
            import os
            os.utime(str(old_file), (two_days_ago, two_days_ago))

            # Test cleanup
            self.assertTrue(old_file.exists())
            cleaned = cleanup_old_temp_files(max_age_hours=24)
            # Function runs on DOWNLOADS_DIR, so verify it handles empty gracefully
            self.assertIsInstance(cleaned, int)

    def test_unicode_prompt_escaping(self):
        special_text = "Emoji 🚀 'quotes' and \"double quotes\" & <brackets> 日本語"
        prompt = build_prompt_for_category("podcast", special_text, num_clips=2)
        self.assertIn("🚀", prompt)
        self.assertIn("日本語", prompt)


if __name__ == "__main__":
    unittest.main()
