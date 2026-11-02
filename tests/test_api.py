"""Integration and Security API Tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from web.server import app  # noqa: E402


class TestWebAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("uptime_seconds", data)
        self.assertIn("cpu_percent", data)
        self.assertIn("hardware", data)

    def test_security_headers_present(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(resp.headers.get("x-frame-options"), "DENY")
        self.assertEqual(resp.headers.get("x-xss-protection"), "1; mode=block")

    def test_config_endpoint_masks_secrets(self):
        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Verify no raw api key has length > 12 without ellipsis
        for key in ["gemini_api_key", "groq_api_key", "openai_api_key"]:
            if key in data and data[key]:
                self.assertIn("...", data[key])

    def test_create_job_input_validation(self):
        # Invalid: Negative clip count
        resp = self.client.post("/api/jobs", json={
            "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "num_clips": -1,
        })
        self.assertEqual(resp.status_code, 422)

        # Invalid: Disallowed category
        resp = self.client.post("/api/jobs", json={
            "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "content_type": "malicious_script_inject",
        })
        self.assertEqual(resp.status_code, 422)

        # Invalid: SSRF target
        resp = self.client.post("/api/jobs", json={
            "source": "http://127.0.0.1:8080/secret",
            "num_clips": 3,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("rejected", resp.json()["detail"].lower())

    def test_get_clip_path_traversal_blocked(self):
        # Path traversal should be rejected with 400 or 404, never 200 or 500
        resp = self.client.get("/api/clips/job_123/../../config.py")
        self.assertIn(resp.status_code, (400, 404))

    def test_create_job_blur_padding_layout(self):
        # Valid: blur_padding layout
        resp = self.client.post("/api/jobs", json={
            "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "layout": "blur_padding",
            "num_clips": 1,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("job_id", resp.json())

    def test_cancel_job_endpoint(self):
        # 404 for non-existent job
        resp = self.client.post("/api/jobs/non_existent_999/cancel")
        self.assertEqual(resp.status_code, 404)

        # Create job and then cancel it
        create_resp = self.client.post("/api/jobs", json={
            "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "num_clips": 1,
        })
        self.assertEqual(create_resp.status_code, 200)
        job_id = create_resp.json()["job_id"]

        cancel_resp = self.client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.json()["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
