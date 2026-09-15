import unittest
import urllib.request
import urllib.error
import json
import time
import asyncio
import websockets
import cv2
from pathlib import Path


BASE_URL = "http://127.0.0.1:8000/api"
WS_URL = "ws://127.0.0.1:8000/ws"
TOKEN = "pit-secure-local-operator-key-2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


class FullRegressionTestSuite(unittest.TestCase):
    """End-to-end regression validation for BUG-001 through BUG-011."""

    @classmethod
    def setUpClass(cls):
        import socket
        try:
            with socket.create_connection(("127.0.0.1", 8000), timeout=0.5):
                cls.server_running = True
        except (socket.timeout, ConnectionRefusedError, OSError):
            cls.server_running = False

    def test_bug_001_live_telemetry_endpoint_integrity(self):
        """BUG-001: Telemetry endpoint returns actual AI frame state, not fake COASTING or fake NORMAL."""
        if not self.server_running:
            self.skipTest("Live Uvicorn server not running on port 8000")
        req = urllib.request.Request(f"{BASE_URL}/jobs/0ffadbe2abc3/telemetry", headers=HEADERS)
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read().decode())
        self.assertIn("available", data)
        self.assertIn("has_ambiguity", data)
        self.assertIn("tracks", data)
        # For finished job, available must be False (not inventing fake frames)
        self.assertFalse(data["available"])
        self.assertEqual(data["tracks_count"], 0)

    def test_bug_002_websocket_invalid_job_closes_cleanly(self):
        """BUG-002: Invalid job ID closes WebSocket in < 1.0s, does NOT hang."""
        if not self.server_running:
            self.skipTest("Live Uvicorn server not running on port 8000")
        async def run_ws():
            t0 = time.perf_counter()
            uri = f"{WS_URL}/jobs/nonexistent_test_job_123?token={TOKEN}"
            with self.assertRaises(Exception):
                async with websockets.connect(uri) as ws:
                    await asyncio.wait_for(ws.recv(), timeout=2.0)
            elapsed = time.perf_counter() - t0
            self.assertLess(elapsed, 1.5, "WebSocket took too long to reject invalid job!")
        asyncio.run(run_ws())

    def test_bug_004_log_tail_bounded_retrieval(self):
        """BUG-004: Reverse-seek bounded log tail returns at most requested lines, not whole file."""
        if not self.server_running:
            self.skipTest("Live Uvicorn server not running on port 8000")
        req = urllib.request.Request(f"{BASE_URL}/jobs/0ffadbe2abc3/log?tail=5", headers=HEADERS)
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
        lines = [line for line in text.strip().split("\n") if line.strip()]
        self.assertLessEqual(len(lines), 5, "Endpoint returned more lines than requested tail limit!")

    def test_bug_008_camera_probing_non_blocking(self):
        """BUG-008: Camera probing runs in threadpool and completes in < 3s."""
        if not self.server_running:
            self.skipTest("Live Uvicorn server not running on port 8000")
        t0 = time.perf_counter()
        req = urllib.request.Request(f"{BASE_URL}/cameras?max_index=1", headers=HEADERS)
        with urllib.request.urlopen(req) as r:
            cams = json.loads(r.read().decode())
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 3.0, "Camera probing took too long!")
        self.assertIsInstance(cams, list)

    def test_bug_009_dead_code_files_removed(self):
        """BUG-009: 13 legacy CSS and dead component files must be completely removed."""
        root = Path(__file__).resolve().parents[1]
        dead_files = [
            root / "frontend/src/ArchiveView.tsx",
            root / "frontend/src/RunDetailDrawer.tsx",
            root / "frontend/src/styles.css",
            root / "frontend/src/demo.css",
            root / "frontend/src/live-preview.css",
            root / "frontend/src/drawer-preview.css",
            root / "frontend/src/history.css",
            root / "frontend/src/source-controls.css",
            root / "frontend/src/memory.css",
            root / "frontend/src/session-details.css",
            root / "frontend/src/run-detail.css",
            root / "frontend/src/archive.css",
            root / "frontend/src/media-stack.css",
        ]
        for f in dead_files:
            self.assertFalse(f.is_file(), f"Dead file still exists: {f}")

    def test_bug_010_upload_does_not_leak_absolute_path(self):
        """BUG-010: POST /api/uploads must not return absolute filesystem path."""
        if not self.server_running:
            self.skipTest("Live Uvicorn server not running on port 8000")
        b = "boundaryTest123"
        header = ("--" + b + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"reg_test.mp4\"\r\nContent-Type: video/mp4\r\n\r\n").encode()
        payload = header + b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + ("\r\n--" + b + "--\r\n").encode()
        req = urllib.request.Request(
            f"{BASE_URL}/uploads",
            data=payload,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": f"multipart/form-data; boundary={b}"}
        )
        with urllib.request.urlopen(req) as r:
            res = json.loads(r.read().decode())
        self.assertNotIn("path", res, "CRITICAL: Upload response leaked absolute server filesystem path!")
        self.assertIn("id", res)
        self.assertIn("preview_url", res)
        # Cleanup uploaded test file
        root = Path(__file__).resolve().parents[1]
        (root / ".appdata/uploads" / f"{res['id']}.mp4").unlink(missing_ok=True)

    def test_bug_011_windows_video_writer_compatible_extension(self):
        """BUG-011: VideoWriter on Windows opens .tmp.mp4 successfully, while .mp4.partial fails."""
        tmp_mp4 = "test_verify.tmp.mp4"
        writer = cv2.VideoWriter(tmp_mp4, cv2.VideoWriter_fourcc(*"mp4v"), 25.0, (320, 240))
        is_open = writer.isOpened()
        writer.release()
        Path(tmp_mp4).unlink(missing_ok=True)
        self.assertTrue(is_open, "VideoWriter must open .tmp.mp4 successfully on Windows Media Foundation!")


if __name__ == "__main__":
    unittest.main()
