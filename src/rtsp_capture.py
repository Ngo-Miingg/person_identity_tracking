from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np


RTSP_OPTIONS = "rtsp_transport;tcp|stimeout;5000000|rw_timeout;5000000|max_delay;500000"
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", RTSP_OPTIONS)


@dataclass(frozen=True)
class CaptureFrame:
    image: np.ndarray
    sequence: int
    captured_at: float


class RtspLatestFrameReader:
    """Own exactly one RTSP capture and expose only its newest decoded frame."""

    def __init__(self, uri: str, *, reconnect_limit: int = 0) -> None:
        self.uri = uri
        self.reconnect_limit = max(int(reconnect_limit), 0)
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._latest: CaptureFrame | None = None
        self._capture: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = False
        self._reconnects = 0
        self._consecutive_failures = 0
        self._last_error = ""
        self._sequence = 0

    def _open(self) -> bool:
        cap = cv2.VideoCapture(self.uri, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            cap.release()
            return False
        self._capture = cap
        self._connected = True
        return True

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="rtsp-latest-frame", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        delay = 0.5
        while not self._stop.is_set():
            if self._capture is None or not self._connected:
                if not self._open():
                    self._consecutive_failures += 1
                    self._last_error = "open_failed"
                    if self.reconnect_limit and self._reconnects >= self.reconnect_limit:
                        break
                    self._stop.wait(delay)
                    delay = min(delay * 2.0, 5.0)
                    continue
                self._reconnects += 1
                delay = 0.5

            ok, frame = self._capture.read()
            if not ok or frame is None or frame.size == 0:
                self._connected = False
                self._consecutive_failures += 1
                self._last_error = "read_failed"
                if self._capture is not None:
                    self._capture.release()
                    self._capture = None
                continue

            now = time.time()
            with self._condition:
                self._sequence += 1
                self._consecutive_failures = 0
                self._last_error = ""
                self._latest = CaptureFrame(frame, self._sequence, now)
                self._condition.notify_all()

    def read(self, timeout: float = 5.0) -> CaptureFrame | None:
        deadline = time.monotonic() + max(float(timeout), 0.0)
        with self._condition:
            current = self._latest.sequence if self._latest is not None else -1
            while not self._stop.is_set():
                if self._latest is not None and self._latest.sequence > current:
                    return self._latest
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # cap.read() runs in the capture thread and can block even
                    # after the socket has gone stale. Force that capture out
                    # of the connected state so the reader loop reconnects.
                    if self._connected:
                        self._connected = False
                        self._consecutive_failures += 1
                        self._last_error = "read_timeout"
                        capture = self._capture
                        self._capture = None
                        if capture is not None:
                            capture.release()
                    return None
                self._condition.wait(remaining)
        return None

    def status(self) -> dict[str, object]:
        with self._lock:
            latest = self._latest
            return {
                "connected": self._connected,
                "sequence": latest.sequence if latest else 0,
                "captured_at": latest.captured_at if latest else None,
                "age_seconds": max(time.time() - latest.captured_at, 0.0) if latest else None,
                "reconnects": self._reconnects,
                "consecutive_failures": self._consecutive_failures,
                "last_error": self._last_error,
            }

    def close(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._connected = False
