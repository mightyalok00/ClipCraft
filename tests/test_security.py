"""Security Unit Tests: SSRF, Path Traversal, and Input Sanitization."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.security import (  # noqa: E402
    is_private_ip,
    mask_secret,
    safe_resolve_path,
    sanitize_filename,
    validate_source,
)


class TestSecurityGuards(unittest.TestCase):
    def test_ssrf_private_ips(self):
        self.assertTrue(is_private_ip("127.0.0.1"))
        self.assertTrue(is_private_ip("10.0.0.1"))
        self.assertTrue(is_private_ip("192.168.1.1"))
        self.assertTrue(is_private_ip("172.16.0.1"))
        self.assertTrue(is_private_ip("169.254.169.254"))  # Cloud metadata
        self.assertFalse(is_private_ip("8.8.8.8"))
        self.assertFalse(is_private_ip("youtube.com"))

    def test_validate_source_allowed_urls(self):
        valid, _ = validate_source("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertTrue(valid)

        valid, _ = validate_source("http://cdn.example.com/video.mp4")
        self.assertTrue(valid)

    def test_validate_source_blocked_schemes(self):
        for bad_url in [
            "file:///etc/passwd",
            "file:///C:/Windows/win.ini",
            "gopher://evil.com/1",
            "ftp://files.example.com",
            "data:text/plain;base64,SGVsbG8=",
        ]:
            valid, msg = validate_source(bad_url)
            self.assertFalse(valid, f"Should have rejected {bad_url}")
            self.assertIn("forbidden", msg.lower())

    def test_validate_source_blocked_ssrf(self):
        for ssrf_url in [
            "http://127.0.0.1:8080/admin",
            "http://localhost:8000/internal",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/secret",
        ]:
            valid, msg = validate_source(ssrf_url)
            self.assertFalse(valid, f"Should have blocked SSRF to {ssrf_url}")
            self.assertIn("blocked", msg.lower())

    def test_validate_source_local_extensions(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            valid_file = Path(tf.name)
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tf:
            bad_file = Path(tf.name)

        try:
            valid, _ = validate_source(str(valid_file), allow_local=True)
            self.assertTrue(valid)

            invalid, msg = validate_source(str(bad_file), allow_local=True)
            self.assertFalse(invalid)
            self.assertIn("unsupported video extension", msg.lower())
        finally:
            valid_file.unlink(missing_ok=True)
            bad_file.unlink(missing_ok=True)

    def test_safe_resolve_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir).resolve()
            # Legitimate path
            safe_path = safe_resolve_path(base, "job_123", "short_01.mp4")
            self.assertTrue(str(safe_path).startswith(str(base)))

            # Malicious traversal attempts
            with self.assertRaises(PermissionError):
                safe_resolve_path(base, "../../../etc", "passwd")

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename("..\\..\\Windows\\win.ini"), "win.ini")
        self.assertEqual(sanitize_filename("clip;rm -rf ;"), "clip_rm_-rf__")

    def test_mask_secret(self):
        self.assertEqual(mask_secret(None), "")
        self.assertEqual(mask_secret(""), "")
        self.assertEqual(mask_secret("1234567"), "********")
        self.assertEqual(mask_secret("AQ.ABCDEFGHI1234"), "AQ.A...1234")


if __name__ == "__main__":
    unittest.main()
