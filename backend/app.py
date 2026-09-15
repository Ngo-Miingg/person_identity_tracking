from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000|rw_timeout;5000000|max_delay;500000",
)
import cv2
import numpy as np

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".appdata"
JOBS_ROOT = APP_ROOT / "jobs"
SOURCES_FILE = APP_ROOT / "sources.json"
CANONICAL_DB = APP_ROOT / "canonical_identity.sqlite"
DEFAULT_HIKVISION_SOURCE_ID = "hikvision-default-01"
DEFAULT_HIKVISION_RTSP = os.environ.get(
    "PIT_HIKVISION_RTSP_URL",
    "rtsp://admin@172.16.16.27:554/Streaming/Channels/101",
)
PYTHON = Path(os.environ.get("PIT_PYTHON", "")) if os.environ.get("PIT_PYTHON") else ROOT.parent / ".venv" / "Scripts" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED_ARTIFACTS = {
    "tracks.csv", "face_observations.csv", "face_temporal.csv",
    "face_identity_diagnostics.csv", "identity_db_face_queries.csv",
    "identity_events.json", "track_summaries.json", "person_memory.json",
    "identity.sqlite", "face_prototypes.npz", "body_prototypes.npz",
    "person_memory_prototypes.npz",
}

# Local console access is intentionally frictionless; deployments can opt into auth.
AUTH_ENABLED = os.environ.get("PIT_AUTH_ENABLED", "false").lower() in {"1", "true", "yes"}
API_KEY = os.environ.get("PIT_API_KEY", "pit-secure-local-operator-key-2026")
COOKIE_NAME = "pit_session_token"
COOKIE_SECURE = os.environ.get("PIT_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}

RETENTION_ENABLED = os.environ.get("PIT_RETENTION_ENABLED", "true").lower() in {"1", "true", "yes"}
RETENTION_DAYS = int(os.environ.get("PIT_RETENTION_DAYS", "14"))
RETENTION_MAX_GB = float(os.environ.get("PIT_RETENTION_MAX_GB", "50.0"))
MIN_FREE_DISK_GB = float(os.environ.get("PIT_MIN_FREE_DISK_GB", "2.0"))
def _configured_backend_workers() -> int:
    """Resolve worker count from explicit env or a directly supplied uvicorn command."""
    explicit = os.environ.get("PIT_MAX_BACKEND_WORKERS")
    if explicit:
        return int(explicit)
    for env_name in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        value = os.environ.get(env_name)
        if value:
            return int(value)
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        for candidate in [proc, *proc.parents()]:
            cmdline = " ".join(candidate.cmdline())
            match = re.search(r"(?:--workers|--worker-count)\s+(\d+)", cmdline)
            if match:
                return int(match.group(1))
    except Exception:
        pass
    return 1


MAX_BACKEND_WORKERS = _configured_backend_workers()

# Enforce single worker startup guard
if MAX_BACKEND_WORKERS > 1:
    raise RuntimeError(
        f"FATAL: MAX_BACKEND_WORKERS={MAX_BACKEND_WORKERS} is unsupported. "
        "The GPU inference engine uses a single shared hardware execution lock. "
        "Backend MUST run with 1 worker process only (PIT_MAX_BACKEND_WORKERS=1)."
    )

# Active short-lived tickets for WebSocket and media access
# Mapping ticket -> (expiry_time, scope)
_active_tickets: dict[str, tuple[float, str]] = {}
_tickets_lock = threading.Lock()

def issue_ticket(scope: str = "general", ttl_seconds: float = 60.0) -> str:
    ticket = secrets.token_hex(16)
    with _tickets_lock:
        now_ts = time.time()
        stale = [k for k, (exp, _) in _active_tickets.items() if exp < now_ts]
        for k in stale:
            _active_tickets.pop(k, None)
        _active_tickets[ticket] = (now_ts + ttl_seconds, scope)
    return ticket

def consume_ticket(ticket: str | None, required_scope: str = "general") -> bool:
    if not ticket:
        return False
    with _tickets_lock:
        entry = _active_tickets.get(ticket)
        if not entry:
            return False
        expiry, scope = entry
        if time.time() > expiry:
            _active_tickets.pop(ticket, None)
            return False
        # Valid short-lived ticket
        return True

def verify_token(token: str | None, auth_header: str | None = None, cookie_token: str | None = None) -> bool:
    # 1. Bearer header or X-API-Key (standard API access)
    if auth_header:
        if auth_header.startswith("Bearer "):
            if auth_header[7:].strip() == API_KEY:
                return True
        if auth_header == API_KEY:
            return True
    # 2. HttpOnly Cookie token (browser session)
    if cookie_token and cookie_token == API_KEY:
        return True
    # 3. Direct API key passed (for automated client testing)
    if token and token == API_KEY:
        return True
    # 4. Short-lived ticket passed via ?ticket= or ?token=
    if token and consume_ticket(token):
        return True
    return False


def now() -> float:
    return time.time()


def safe_job_path(job_id: str) -> Path:
    if not job_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in job_id):
        raise HTTPException(400, "Invalid job id")
    path = JOBS_ROOT / job_id
    if not path.is_dir():
        raise HTTPException(404, "Job not found")
    return path


def safe_upload_id(upload_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]{12}", upload_id):
        raise HTTPException(400, "Invalid upload id")
    matches = list((APP_ROOT / "uploads").glob(f"{upload_id}.*"))
    if len(matches) != 1 or not matches[0].is_file():
        raise HTTPException(404, "Upload not found")
    return matches[0]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_sources() -> list[dict[str, Any]]:
    sources = read_json(SOURCES_FILE, [])
    if not isinstance(sources, list):
        sources = []
    if not any(
        item.get("kind") == "rtsp" and item.get("uri") == DEFAULT_HIKVISION_RTSP
        for item in sources
        if isinstance(item, dict)
    ):
        sources.append({
            "id": DEFAULT_HIKVISION_SOURCE_ID,
            "name": "Hikvision Camera 172.16.16.27",
            "kind": "rtsp",
            "uri": DEFAULT_HIKVISION_RTSP,
            "location": "Default Hikvision RTSP",
            "enabled": True,
        })
        write_json(SOURCES_FILE, sources)
    return sources


def public_source(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    uri = str(result.get("uri", ""))
    parsed = urlsplit(uri)
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        if parsed.port:
            host += f":{parsed.port}"
        result["uri"] = urlunsplit((parsed.scheme, f"***:***@{host}", parsed.path, parsed.query, parsed.fragment))
    return result


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern="^(upload|webcam|rtsp)$")
    uri: str = Field(default="", max_length=2048)
    location: str = Field(default="", max_length=120)
    enabled: bool = True


class JobIn(BaseModel):
    source_id: str | None = None
    source: str | None = None
    name: str = Field(default="Identity tracking job", max_length=100)
    device: str = "0"
    gallery: str | None = None
    canonical_db: str | None = None
    extra_args: list[str] = Field(default_factory=list, max_length=40)


@dataclass
class Job:
    id: str
    name: str
    source: str
    source_label: str
    source_kind: str = "upload"
    preview_url: str | None = None
    status: str = "QUEUED"
    created_at: float = field(default_factory=now)
    started_at: float | None = None
    finished_at: float | None = None
    return_code: int | None = None
    error: str | None = None
    cancel_requested_at: float | None = None
    pid: int | None = None
    process_create_time: float | None = None
    updated_at: float = field(default_factory=now)
    process: subprocess.Popen[str] | None = field(default=None, repr=False, compare=False)
    thread: threading.Thread | None = field(default=None, repr=False, compare=False)
    _progress_cache_key: tuple[Any, ...] | None = field(default=None, repr=False, compare=False)
    _progress_cache: dict[str, Any] | None = field(default=None, repr=False, compare=False)

    def public(self) -> dict[str, Any]:
        result = {
            "id": self.id, "name": self.name, "source": self.source,
            "source_label": self.source_label, "status": self.status,
            "source_kind": self.source_kind, "preview_url": self.preview_url,
            "created_at": self.created_at, "started_at": self.started_at,
            "finished_at": self.finished_at, "return_code": self.return_code,
            "error": self.error, "cancel_requested_at": self.cancel_requested_at,
            "pid": self.pid, "process_create_time": self.process_create_time, "updated_at": self.updated_at,
        }
        result["progress"] = self.progress()
        result["artifacts"] = artifact_manifest(JOBS_ROOT / self.id / "output", self.status)
        result["media"] = media_descriptor(self)
        return result

    def progress(self) -> dict[str, Any]:
        output = JOBS_ROOT / self.id / "output"
        tracks = output / "tracks.csv"
        telemetry = output / "live" / "telemetry.json"
        cache_key = (self.status, tuple(
            (path.stat().st_mtime_ns, path.stat().st_size) if path.is_file() else None
            for path in (tracks, telemetry)
        ))
        if self._progress_cache_key == cache_key and self._progress_cache is not None:
            return dict(self._progress_cache)
        rows = 0
        recorded_frames = 0
        if tracks.is_file():
            try:
                with tracks.open(newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        rows += 1
                        if row.get("frame") not in {None, ""}:
                            recorded_frames = max(recorded_frames, int(float(row["frame"])) + 1)
            except (OSError, TypeError, ValueError):
                pass
        frames = recorded_frames
        if telemetry.is_file():
            t_data = read_json(telemetry, None)
            if isinstance(t_data, dict) and "frame" in t_data:
                frames = max(0, int(t_data.get("frame", 0)) + 1)
        live = output / "live"
        live_images = len(list(live.glob("*.jpg"))) if live.is_dir() else 0
        phase = "finished" if self.status == "COMPLETED" else "failed" if self.status == "FAILED" else "stopped" if self.status == "STOPPED" else self.status.lower()
        result = {"rows": rows, "frames": frames, "live_images": live_images, "phase": phase}
        self._progress_cache_key = cache_key
        self._progress_cache = result
        return dict(result)


def _get_process_create_time(pid: int) -> float | None:
    try:
        import psutil
        p = psutil.Process(pid)
        return p.create_time()
    except Exception:
        return None


def _kill_process_tree(pid: int | None, job_id: str | None = None, expected_create_time: float | None = None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        import psutil
        try:
            target_proc = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

        # If expected creation time is known, guard against PID reuse
        if expected_create_time is not None:
            actual_create_time = target_proc.create_time()
            if abs(actual_create_time - expected_create_time) > 2.0:
                print(f"[PID-REUSE-GUARD] Stale PID {pid} detected: actual create_time={actual_create_time} vs expected={expected_create_time}. Skipping kill.")
                return False

        # Verify process command line contains python and (infer.py or job_id or python.exe)
        try:
            cmdline = " ".join(target_proc.cmdline()).lower()
            if "python" not in cmdline:
                print(f"[PID-REUSE-GUARD] Process {pid} is not a python process: '{cmdline}'. Skipping kill.")
                return False
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        # Terminate children first, then parent
        children = target_proc.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        target_proc.kill()
        return True
    except Exception as e:
        print(f"[PID-REUSE-GUARD] Error killing process {pid}: {e}")
        return False


def validate_completed_artifacts(output: Path, source_kind: str) -> str | None:
    """Return a concrete validation error instead of publishing an incomplete run."""
    required_json = ("identity_events.json", "track_summaries.json", "person_memory.json")
    required_npz = ("face_prototypes.npz", "body_prototypes.npz", "person_memory_prototypes.npz")
    required_files = ("tracks.csv", "identity.sqlite", *required_json, *required_npz)
    missing = [name for name in required_files if not (output / name).is_file()]
    if missing:
        return f"infer.py exited successfully but required artifacts are missing: {', '.join(missing)}"
    try:
        for name in required_json:
            with (output / name).open(encoding="utf-8") as handle:
                json.load(handle)
        for name in required_npz:
            with np.load(output / name, allow_pickle=False) as archive:
                list(archive.files)
        connection = sqlite3.connect(output / "identity.sqlite")
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            required_tables = {"identities", "tracklets", "detections", "observations", "assignments", "identity_events", "fusion_decisions"}
            actual_tables = {
                row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            missing_tables = required_tables - actual_tables
            if missing_tables:
                return f"identity.sqlite schema is incomplete; missing tables: {', '.join(sorted(missing_tables))}"
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                return f"identity.sqlite has {len(foreign_key_errors)} foreign-key violations"
            invalid_intervals = connection.execute(
                "SELECT COUNT(*) FROM assignments WHERE valid_to IS NOT NULL AND valid_to < valid_from"
            ).fetchone()[0]
            if invalid_intervals:
                return f"identity.sqlite has {invalid_intervals} invalid assignment intervals"
        finally:
            connection.close()
        if not integrity or integrity[0] != "ok":
            return "infer.py exited successfully but identity.sqlite failed its integrity check"
    except Exception as exc:
        return f"infer.py exited successfully but artifact validation failed: {exc}"

    if source_kind == "upload":
        videos = [path for path in output.glob("*_identity.mp4") if not path.name.endswith("_local_identity.mp4")]
        if not videos:
            videos = list(output.glob("*_local_identity.mp4"))
        valid_video = False
        for path in videos:
            if path.stat().st_size <= 0:
                continue
            capture = cv2.VideoCapture(str(path))
            try:
                valid_video = capture.isOpened() and capture.get(cv2.CAP_PROP_FRAME_COUNT) >= 1
            finally:
                capture.release()
            if valid_video:
                break
        if not valid_video:
            return "infer.py exited successfully but no valid completed MP4 was produced"
    return None


class CrossProcessExecutionLock:
    """Provides a unified cross-process file lock + threading lock for GPU worker execution."""
    def __init__(self, lock_file: Path) -> None:
        self.lock_file = lock_file
        self.thread_lock = threading.Lock()
        self._fd: int | None = None

    def acquire(self) -> None:
        self.thread_lock.acquire()
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        # Spin until file lock is acquired
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    # Open without sharing or open with read/write
                    fd = os.open(str(self.lock_file), os.O_CREAT | os.O_RDWR)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    self._fd = fd
                    break
                else:
                    import fcntl
                    fd = os.open(str(self.lock_file), os.O_CREAT | os.O_RDWR)
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._fd = fd
                    break
            except (OSError, IOError):
                time.sleep(0.1)

    def release(self) -> None:
        try:
            if self._fd is not None:
                if sys.platform == "win32":
                    import msvcrt
                    try:
                        msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                else:
                    import fcntl
                    try:
                        fcntl.flock(self._fd, fcntl.LOCK_UN)
                    except Exception:
                        pass
                os.close(self._fd)
                self._fd = None
        finally:
            if self.thread_lock.locked():
                self.thread_lock.release()


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.lock = threading.RLock()
        self.execution_lock = CrossProcessExecutionLock(APP_ROOT / "gpu_execution.lock")
        APP_ROOT.mkdir(parents=True, exist_ok=True)
        JOBS_ROOT.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    def _load_existing(self) -> None:
        queued: list[tuple[Job, dict[str, Any]]] = []
        for status_path in JOBS_ROOT.glob("*/status.json"):
            status = read_json(status_path, None)
            if not isinstance(status, dict) or not status.get("id"):
                continue
            status_value = status.get("status", "UNKNOWN")
            pid = status.get("pid")
            create_time = status.get("process_create_time")
            if status_value in {"RUNNING", "CANCEL_REQUESTED"}:
                status_value = "FAILED" if status_value == "RUNNING" else "STOPPED"
                status["status"] = status_value
                status["error"] = "Worker was restarted while this job was running" if status_value == "FAILED" else "Cancellation completed during backend restart"
                if pid:
                    _kill_process_tree(pid, job_id=status.get("id"), expected_create_time=create_time)
                status["finished_at"] = status.get("finished_at") or now()
                status["updated_at"] = now()
                status["pid"] = None
                status["process_create_time"] = None
                write_json(status_path, status)
            job = Job(
                id=status["id"], name=status.get("name", status["id"]), source=status.get("source", ""),
                source_label=status.get("source_label", status.get("source", "")), source_kind=status.get("source_kind", "upload"),
                preview_url=status.get("preview_url"), status=status_value, created_at=status.get("created_at", now()),
                started_at=status.get("started_at"), finished_at=status.get("finished_at"), return_code=status.get("return_code"),
                error=status.get("error"), cancel_requested_at=status.get("cancel_requested_at"),
                pid=status.get("pid"), process_create_time=status.get("process_create_time"), updated_at=status.get("updated_at", now()),
            )
            self.jobs[job.id] = job
            if job.status == "QUEUED":
                request_data = self._read_request(job.id)
                if request_data is None:
                    job.status = "FAILED"
                    job.error = "Queued job cannot be recovered because request.json is missing or invalid"
                    job.finished_at = now()
                    job.updated_at = job.finished_at
                    write_json(status_path, job.public())
                else:
                    queued.append((job, request_data))
        for job, request_data in sorted(queued, key=lambda item: item[0].created_at):
            self._start_thread(job, request_data)

    def _read_request(self, job_id: str) -> dict[str, Any] | None:
        payload = read_json(JOBS_ROOT / job_id / "request.json", None)
        if not isinstance(payload, dict) or not isinstance(payload.get("device"), str):
            return None
        extra_args = payload.get("extra_args", [])
        if not isinstance(extra_args, list) or not all(isinstance(arg, str) for arg in extra_args):
            return None
        return {
            "device": payload["device"],
            "gallery": payload.get("gallery") if isinstance(payload.get("gallery"), str) else None,
            "canonical_db": payload.get("canonical_db") if isinstance(payload.get("canonical_db"), str) else None,
            "extra_args": list(extra_args),
        }

    def _start_thread(self, job: Job, request_data: dict[str, Any]) -> None:
        job.thread = threading.Thread(
            target=self._run,
            args=(job, request_data["device"], request_data["gallery"], request_data["canonical_db"], request_data["extra_args"]),
            daemon=True,
            name=f"identity-job-{job.id}",
        )
        job.thread.start()

    def submit(self, name: str, source: str, source_label: str, source_kind: str, preview_url: str | None,
               device: str, gallery: str | None, canonical_db: str | None, extra_args: list[str]) -> Job:
        job_id = uuid.uuid4().hex[:12]
        root = JOBS_ROOT / job_id
        (root / "input").mkdir(parents=True)
        (root / "output").mkdir()
        (root / "logs").mkdir()
        job = Job(job_id, name, source, source_label, source_kind, f"/api/jobs/{job_id}/overlay")
        with self.lock:
            self.jobs[job_id] = job
        canonical_db = canonical_db or str(CANONICAL_DB)
        write_json(root / "request.json", {"name": name, "source": source, "source_label": source_label, "source_kind": source_kind, "device": device, "gallery": gallery, "canonical_db": canonical_db, "extra_args": extra_args})
        write_json(root / "status.json", job.public())
        self._start_thread(job, {"device": device, "gallery": gallery, "canonical_db": canonical_db, "extra_args": list(extra_args)})
        return job

    def _run(self, job: Job, device: str, gallery: str | None, canonical_db: str | None, extra_args: list[str]) -> None:
        root = JOBS_ROOT / job.id
        log_path = root / "logs" / "worker.log"
        output = root / "output"
        command = [str(PYTHON), str(ROOT / "infer.py"), "--sources", job.source,
                   "--output", str(output), "--device", device]
        if gallery:
            command += ["--gallery", gallery]
        if canonical_db:
            command += ["--canonical-db", canonical_db]
            command += ["--canonical-output", canonical_db]
        command += extra_args
        self.execution_lock.acquire()
        try:
            if job.status in {"STOPPED", "CANCEL_REQUESTED"}:
                return
            with self.lock:
                job.status = "RUNNING"
                job.started_at = now()
            write_json(root / "status.json", job.public())
            env = os.environ.copy()
            env.setdefault("PIT_WORKSPACE_ROOT", str(ROOT.parent))
            env.setdefault("PIT_ASSETS_ROOT", str(ROOT))
            with log_path.open("w", encoding="utf-8", errors="replace") as log:
                log.write("$ " + " ".join(command) + "\n\n")
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
                create_time = _get_process_create_time(process.pid)
                with self.lock:
                    job.process = process
                    job.pid = process.pid
                    job.process_create_time = create_time
                    job.updated_at = now()
                write_json(root / "status.json", job.public())
                code = process.wait()
            with self.lock:
                job.return_code = code
                job.updated_at = now()
                if job.status not in {"STOPPED", "CANCEL_REQUESTED"}:
                    artifact_error = validate_completed_artifacts(output, job.source_kind) if code == 0 else None
                    job.status = "COMPLETED" if code == 0 and artifact_error is None else "FAILED"
                    job.error = artifact_error if code == 0 else f"infer.py exited with code {code}; open worker.log for the traceback"
                elif job.status == "CANCEL_REQUESTED":
                    job.status = "STOPPED"
        except Exception as exc:
            with self.lock:
                job.status = "STOPPED" if job.status == "CANCEL_REQUESTED" else "FAILED"
                job.error = "Stopped by user" if job.status == "STOPPED" else str(exc)
                job.updated_at = now()
        finally:
            with self.lock:
                job.finished_at = now()
                job.process = None
                job.pid = None
                job.process_create_time = None
                job.updated_at = now()
            write_json(root / "status.json", job.public())
            self.execution_lock.release()

    def get(self, job_id: str) -> Job:
        with self.lock:
            job = self.jobs.get(job_id)
        if job:
            return job
        status = read_json(JOBS_ROOT / job_id / "status.json", None)
        if status:
            job = Job(status["id"], status["name"], status["source"], status.get("source_label", status["source"]),
                      status.get("source_kind", "upload"), status.get("preview_url"), status.get("status", "UNKNOWN"),
                      status.get("created_at", now()), status.get("started_at"),
                       status.get("finished_at"), status.get("return_code"), status.get("error"), status.get("cancel_requested_at"),
                       pid=status.get("pid"), process_create_time=status.get("process_create_time"), updated_at=status.get("updated_at", now()))
            self.jobs[job_id] = job
            return job
        raise HTTPException(404, "Job not found")

    def stop(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status == "QUEUED":
            job.status = "STOPPED"
            job.error = "Stopped by user before execution"
            job.finished_at = now()
            job.cancel_requested_at = job.finished_at
            job.updated_at = now()
            write_json(JOBS_ROOT / job.id / "status.json", job.public())
            return job
        if job.process and job.status == "RUNNING":
            job.status = "CANCEL_REQUESTED"
            job.cancel_requested_at = now()
            job.updated_at = now()
            _kill_process_tree(job.process.pid, job_id=job.id, expected_create_time=job.process_create_time)
            try:
                job.process.terminate()
            except Exception:
                pass
            job.error = "Stopped by user"
            write_json(JOBS_ROOT / job.id / "status.json", job.public())
        return job


def artifact_manifest(output: Path, job_status: str = "UNKNOWN") -> list[dict[str, Any]]:
    if not output.is_dir():
        return []
    items = []
    for path in sorted(output.iterdir()):
        if path.name in ALLOWED_ARTIFACTS or path.name.endswith("_identity.mp4") or path.name.endswith("_local_identity.mp4"):
            if path.is_file():
                state = "READY" if job_status == "COMPLETED" else "PARTIAL" if job_status in {"STOPPED", "FAILED"} else "WRITING"
                items.append({"name": path.name, "size": path.stat().st_size, "state": state, "role": "download" if path.suffix.lower() == ".mp4" else "evidence", "playback": False if path.suffix.lower() == ".mp4" else None})
    return items


def media_descriptor(job: Job) -> dict[str, Any]:
    output = JOBS_ROOT / job.id / "output"
    live = output / "live"
    live_files = list(live.glob("*.jpg")) if live.is_dir() else []
    videos = [p for p in output.glob("*_identity.mp4") if not p.name.endswith("_local_identity.mp4")]
    if not videos:
        videos = list(output.glob("*_local_identity.mp4"))
    return {
        "state": "LIVE" if job.status in {"RUNNING", "CANCEL_REQUESTED"} else "READY" if job.status == "COMPLETED" and (videos or live_files) else "PARTIAL" if videos or live_files else "UNAVAILABLE",
        "consistency": "LIVE_PROVISIONAL" if job.status in {"RUNNING", "CANCEL_REQUESTED"} else "FINAL_RECONCILED" if job.status == "COMPLETED" else "PARTIAL_UNRECONCILED",
        "live_url": f"/api/jobs/{job.id}/media/live.mjpeg" if job.status in {"RUNNING", "CANCEL_REQUESTED"} else None,
        "snapshot_url": f"/api/jobs/{job.id}/media/snapshot.jpg",
        "playback_url": f"/api/jobs/{job.id}/artifacts/{videos[0].name}" if job.status == "COMPLETED" and videos else None,
        "download_url": f"/api/jobs/{job.id}/artifacts/{videos[0].name}" if videos else None,
        "warning": None if job.status == "COMPLETED" and videos else "No completed MP4 is available for replay." if job.status == "COMPLETED" else None,
    }


manager = JobManager()
app = FastAPI(title="Person Identity Tracking Console", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                  allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not AUTH_ENABLED or path in {"/api/health", "/api/auth/session", "/docs", "/openapi.json"} or not path.startswith("/api/"):
        return await call_next(request)
    auth_header = request.headers.get("Authorization") or request.headers.get("X-API-Key")
    query_token = request.query_params.get("token") or request.query_params.get("ticket")
    cookie_token = request.cookies.get(COOKIE_NAME)
    if not verify_token(query_token, auth_header, cookie_token):
        response = Response(content='{"detail":"Authentication required: invalid or missing API token"}', status_code=401, media_type="application/json")
        origin = request.headers.get("origin")
        if origin in {"http://localhost:5173", "http://127.0.0.1:5173"}:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
        return response
    return await call_next(request)


@app.post("/api/auth/session")
def create_session(response: Response, request: Request) -> dict[str, Any]:
    """Establishes a secure HttpOnly session cookie from a valid API key or Bearer token."""
    auth_header = request.headers.get("Authorization") or request.headers.get("X-API-Key")
    token = request.query_params.get("token")
    if not verify_token(token, auth_header):
        raise HTTPException(401, "Invalid API token for session creation")
    response.set_cookie(
        key=COOKIE_NAME,
        value=API_KEY,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=86400 * 7,  # 7 days
    )
    return {"ok": True, "session": "active", "scope": "single-operator"}


@app.get("/api/auth/session")
def session_status(request: Request) -> dict[str, Any]:
    if not verify_token(None, request.headers.get("Authorization"), request.cookies.get(COOKIE_NAME)):
        raise HTTPException(401, "Operator session is missing or expired")
    return {"ok": True, "session": "active", "scope": "single-operator"}


@app.post("/api/auth/ticket")
def request_access_ticket(scope: str = "media") -> dict[str, str]:
    """Issues a short-lived one-time ticket (60s) for WebSocket or Media Streaming without exposing master key."""
    ticket = issue_ticket(scope=scope, ttl_seconds=60.0)
    return {"ticket": ticket, "expires_in": 60}


def _dir_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


@app.get("/api/storage")
def storage_metrics() -> dict[str, Any]:
    import shutil
    total, used, free = shutil.disk_usage(ROOT)
    uploads_size = _dir_size(APP_ROOT / "uploads")
    jobs_size = _dir_size(JOBS_ROOT)
    return {
        "disk_total_bytes": total,
        "disk_used_bytes": used,
        "disk_free_bytes": free,
        "uploads_size_bytes": uploads_size,
        "jobs_size_bytes": jobs_size,
        "retention": {
            "enabled": RETENTION_ENABLED,
            "days": RETENTION_DAYS,
            "max_gb": RETENTION_MAX_GB,
        }
    }


def _ensure_disk_safety(required_bytes: int = 100 * 1024 * 1024) -> None:
    """Rejects operations if remaining free disk space is below MIN_FREE_DISK_GB."""
    import shutil
    try:
        _, _, free = shutil.disk_usage(ROOT)
        min_free_bytes = int(MIN_FREE_DISK_GB * 1024 * 1024 * 1024)
        if free - required_bytes < min_free_bytes:
            free_gb = round(free / (1024**3), 2)
            raise HTTPException(
                507,
                f"Insufficient disk storage: {free_gb} GB free, but system safety policy requires at least {MIN_FREE_DISK_GB} GB remaining."
            )
    except HTTPException:
        raise
    except Exception:
        pass


def auto_prune_if_exceeded() -> dict[str, Any]:
    """Automatically prunes completed/failed jobs older than cutoff or if total jobs size exceeds RETENTION_MAX_GB."""
    if not RETENTION_ENABLED:
        return {"pruned": False, "reason": "retention_disabled"}
    return prune_storage(dry_run=False)


@app.post("/api/storage/prune")
def prune_storage(dry_run: bool = True) -> dict[str, Any]:
    cutoff = now() - (RETENTION_DAYS * 86400)
    pruned_jobs = []
    freed_bytes = 0
    max_bytes = int(RETENTION_MAX_GB * 1024 * 1024 * 1024)
    
    # 1. First pass: Collect eligible terminal jobs (never delete RUNNING, QUEUED, or CANCEL_REQUESTED)
    candidate_jobs = []
    for job_dir in JOBS_ROOT.iterdir():
        if not job_dir.is_dir():
            continue
        status_file = job_dir / "status.json"
        if not status_file.is_file():
            continue
        status = read_json(status_file, {})
        st = status.get("status")
        if st in {"RUNNING", "QUEUED", "CANCEL_REQUESTED"}:
            continue
        created = status.get("created_at", 0)
        size = _dir_size(job_dir)
        candidate_jobs.append((created, size, job_dir, st))

    # Sort oldest first
    candidate_jobs.sort(key=lambda x: x[0])
    current_jobs_size = _dir_size(JOBS_ROOT)

    for created, size, job_dir, st in candidate_jobs:
        # Prune if older than RETENTION_DAYS OR if current size exceeds quota
        if created < cutoff or current_jobs_size > max_bytes:
            pruned_jobs.append({"id": job_dir.name, "status": st, "size": size})
            freed_bytes += size
            current_jobs_size -= size
            if not dry_run:
                import shutil
                shutil.rmtree(job_dir, ignore_errors=True)
                with manager.lock:
                    manager.jobs.pop(job_dir.name, None)

    return {
        "dry_run": dry_run,
        "pruned_jobs_count": len(pruned_jobs),
        "freed_bytes": freed_bytes,
        "pruned_jobs": pruned_jobs,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "identity-tracking-console", "jobs": len(manager.jobs)}


@app.get("/api/sources")
def sources() -> list[dict[str, Any]]:
    return [public_source(x) for x in load_sources()]


def _probe_cameras_worker(max_index: int = 5) -> list[dict[str, Any]]:
    detected: list[dict[str, Any]] = []
    for index in range(max(0, min(max_index + 1, 16))):
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        try:
            if not capture.isOpened():
                continue
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            detected.append({"index": index, "label": f"Laptop / USB camera {index}", "width": int(frame.shape[1]), "height": int(frame.shape[0])})
        except Exception:
            pass
        finally:
            capture.release()
    return detected


@app.get("/api/cameras")
async def cameras(max_index: int = Query(default=5, ge=0, le=15)) -> list[dict[str, Any]]:
    return await run_in_threadpool(_probe_cameras_worker, max_index)


@app.post("/api/sources")
def create_source(payload: SourceIn) -> dict[str, Any]:
    items = load_sources()
    item = {"id": uuid.uuid4().hex[:10], **payload.model_dump()}
    items.append(item)
    write_json(SOURCES_FILE, items)
    return public_source(item)


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str) -> dict[str, bool]:
    current = load_sources()
    removed = next((x for x in current if x.get("id") == source_id), None)
    if removed:
        for job in list(manager.jobs.values()):
            if job.status == "RUNNING" and (job.source == removed.get("uri") or job.source_label == removed.get("name")):
                manager.stop(job.id)
    items = [x for x in current if x.get("id") != source_id]
    write_json(SOURCES_FILE, items)
    return {"ok": True}


def _is_valid_video_container(header: bytes) -> bool:
    if len(header) < 8:
        return False
    # Reject Windows executable (PE / MZ)
    if header.startswith(b"MZ"):
        return False
    # MP4 / MOV / QuickTime
    if b"ftyp" in header[4:16] or b"moov" in header[4:16]:
        return True
    # AVI
    if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"AVI ":
        return True
    # Matroska / WebM
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return True
    return False


@app.post("/api/uploads")
async def upload_video(file: UploadFile = File(...)) -> dict[str, str]:
    _ensure_disk_safety(required_bytes=100 * 1024 * 1024)
    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in {".mp4", ".avi", ".mov", ".mkv", ".webm"}:
        raise HTTPException(415, "Unsupported video format")
    header = await file.read(1024)
    if not _is_valid_video_container(header):
        raise HTTPException(415, "Invalid or corrupt video container format")
    upload_id = uuid.uuid4().hex[:12]
    target = APP_ROOT / "uploads" / f"{upload_id}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    size = len(header)
    with target.open("wb") as out:
        out.write(header)
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                target.unlink(missing_ok=True)
                raise HTTPException(413, "Video is too large")
            out.write(chunk)
    return {"id": upload_id, "name": file.filename or target.name, "preview_url": f"/api/uploads/{upload_id}/mjpeg"}


@app.get("/api/uploads/{upload_id}")
def uploaded_video(upload_id: str):
    path = safe_upload_id(upload_id)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/uploads/{upload_id}/mjpeg")
def uploaded_mjpeg(upload_id: str):
    return StreamingResponse(mjpeg_frames(str(safe_upload_id(upload_id))), media_type="multipart/x-mixed-replace; boundary=frame")


def _open_capture(source: str | int) -> cv2.VideoCapture:
    """Open a capture with bounded RTSP waits and a one-frame live buffer."""
    if isinstance(source, str) and source.startswith(("rtsp://", "http://", "https://")):
        # OpenCV 5 rejects these properties when passed to open(); timeout
        # values are supplied through OPENCV_FFMPEG_CAPTURE_OPTIONS above.
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap
    return cv2.VideoCapture(source)


def mjpeg_frames(source: str):
    capture_source: str | int = int(source) if source.isdigit() else source
    is_live = isinstance(capture_source, str) and capture_source.startswith(("rtsp://", "http://", "https://"))
    cap = _open_capture(capture_source)
    reconnect_delay = 0.5
    try:
        while True:
            if not cap.isOpened():
                if not is_live:
                    break
                cap.release()
                time.sleep(reconnect_delay)
                cap = _open_capture(capture_source)
                reconnect_delay = min(reconnect_delay * 2, 5.0)
                continue
            ok, frame = cap.read()
            if not ok:
                if is_live:
                    cap.release()
                    time.sleep(reconnect_delay)
                    cap = _open_capture(capture_source)
                    reconnect_delay = min(reconnect_delay * 2, 5.0)
                    continue
                break
            reconnect_delay = 0.5
            ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
            if ok:
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(encoded)).encode() + b"\r\n\r\n" + encoded.tobytes() + b"\r\n"
            time.sleep(0.03)
    finally:
        cap.release()


@app.get("/api/sources/{source_id}/mjpeg")
def source_mjpeg(source_id: str):
    source = next((x for x in load_sources() if x.get("id") == source_id), None)
    if not source:
        raise HTTPException(404, "Source not found")
    if source.get("kind") == "upload":
        raise HTTPException(400, "Use the upload video endpoint for file sources")
    active_job = next(
        (item for item in manager.jobs.values()
         if item.status in {"RUNNING", "CANCEL_REQUESTED"} and item.source == source.get("uri")),
        None,
    )
    if active_job is not None:
        return StreamingResponse(
            overlay_stream(active_job.id),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )
    return StreamingResponse(mjpeg_frames(str(source.get("uri", "0"))), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/jobs")
def create_job(payload: JobIn) -> dict[str, Any]:
    _ensure_disk_safety(required_bytes=200 * 1024 * 1024)
    if payload.device != "0":
        raise HTTPException(400, "This console is locked to NVIDIA GeForce RTX 3050 (CUDA:0)")
    # Check if storage prune is needed before accepting new job
    auto_prune_if_exceeded()
    forbidden = {"--sources", "--output", "--identity-db", "--canonical-db", "--canonical-output", "--gallery"}
    if any(arg in forbidden or any(arg.startswith(name + "=") for name in forbidden) for arg in payload.extra_args):
        raise HTTPException(400, "Protected infer arguments cannot be overridden")
    source = payload.source
    label = source or ""
    source_kind = "upload"
    preview_url: str | None = None
    if payload.source_id:
        source_item = next((x for x in load_sources() if x.get("id") == payload.source_id), None)
        if not source_item:
            raise HTTPException(404, "Source not found")
        if not source_item.get("enabled", True):
            raise HTTPException(409, "Source is disabled")
        source = source_item.get("uri", "")
        label = source_item.get("name", source)
        source_kind = str(source_item.get("kind", "upload"))
        if source_kind == "upload":
            upload_id = Path(source).stem
            if re.fullmatch(r"[a-z0-9]{12}", upload_id):
                preview_url = f"/api/uploads/{upload_id}/mjpeg"
        else:
            preview_url = f"/api/sources/{payload.source_id}/mjpeg"
    elif source and str(source).lower().startswith("rtsp://"):
        source_kind = "rtsp"
        label = "RTSP source"
    elif source and re.fullmatch(r"\d+", str(source)):
        source_kind = "webcam"
        label = f"Camera {source}"
    if not source:
        raise HTTPException(400, "A source is required")
    if source_kind == "webcam" and not re.fullmatch(r"\d+", str(source)):
        raise HTTPException(400, "Webcam source must use a numeric backend camera index")
    if source_kind == "upload" and not Path(source).is_file():
        upload_id = Path(source).stem
        if re.fullmatch(r"[a-z0-9]{12}", upload_id):
            upload_file = safe_upload_id(upload_id)
            source = str(upload_file)
    if source.startswith("/") and not Path(source).exists() and not source.startswith("/dev/"):
        raise HTTPException(400, "Source file does not exist")
    job = manager.submit(payload.name, source, label, source_kind, preview_url, payload.device, payload.gallery, payload.canonical_db, payload.extra_args)
    return job.public()


def overlay_frame(frame: Any) -> bytes | None:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    return encoded.tobytes() if ok else None


def overlay_stream(job_id: str):
    job = manager.get(job_id)
    output = JOBS_ROOT / job.id / "output"
    live_files = list((output / "live").glob("*.jpg")) if (output / "live").is_dir() else []
    live_path = live_files[0] if live_files else output / "live" / "current.jpg"
    last_live_mtime = 0.0
    stale_since = time.monotonic()
    try:
        while True:
            if not live_path.is_file() and (output / "live").is_dir():
                candidates = list((output / "live").glob("*.jpg"))
                if candidates:
                    live_path = candidates[0]
            if live_path.is_file():
                mtime = live_path.stat().st_mtime
                if mtime > last_live_mtime:
                    last_live_mtime = mtime
                    stale_since = time.monotonic()
                    payload = live_path.read_bytes()
                    yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload + b"\r\n"
                    continue
            if job.status not in {"RUNNING", "CANCEL_REQUESTED"}:
                break
            if time.monotonic() - stale_since > 15.0:
                break
            time.sleep(0.03)
    finally:
        return


@app.get("/api/jobs/{job_id}/overlay")
def job_overlay(job_id: str):
    return StreamingResponse(overlay_stream(job_id), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/jobs/{job_id}/media")
def job_media(job_id: str):
    return manager.get(job_id).public()["media"]


@app.get("/api/jobs/{job_id}/telemetry")
def job_telemetry(job_id: str) -> dict[str, Any]:
    job = manager.get(job_id)
    output = JOBS_ROOT / job.id / "output"
    telemetry_path = output / "live" / "telemetry.json"
    if telemetry_path.is_file():
        data = read_json(telemetry_path, None)
        if isinstance(data, dict):
            return {"job_id": job.id, "status": job.status, **data}
    return {
        "job_id": job.id,
        "status": job.status,
        "available": False,
        "frame": -1,
        "camera": None,
        "timestamp": None,
        "tracks_count": 0,
        "has_ambiguity": False,
        "tracks": [],
    }


@app.get("/api/jobs/{job_id}/events")
def job_biometric_events(job_id: str, limit: int = 200) -> dict[str, Any]:
    """Return persisted ticker events so navigation/refresh can recover history."""
    output = identity_output(job_id)
    path = output / "live" / "biometric_events.jsonl"
    safe_limit = max(1, min(int(limit), 1000))
    if not path.is_file():
        return {"job_id": job_id, "events": []}
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as event_file:
        for line in event_file:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("event_id"):
                events.append(value)
    unique: dict[str, dict[str, Any]] = {str(event["event_id"]): event for event in events}
    return {"job_id": job_id, "events": list(unique.values())[-safe_limit:]}


@app.get("/api/jobs/{job_id}/media/live.mjpeg")
def job_live_media(job_id: str):
    job = manager.get(job_id)
    if job.status not in {"RUNNING", "CANCEL_REQUESTED"}:
        raise HTTPException(409, "Live media is not available for this job")
    return StreamingResponse(overlay_stream(job_id), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}/snapshot")
def job_snapshot(job_id: str):
    job = manager.get(job_id)
    output = JOBS_ROOT / job.id / "output"
    live_files = list((output / "live").glob("*.jpg")) if (output / "live").is_dir() else []
    if live_files:
        return FileResponse(max(live_files, key=lambda path: path.stat().st_mtime), media_type="image/jpeg", headers={"Cache-Control": "no-store, max-age=0"})
    videos = [path for path in output.glob("*_identity.mp4") if not path.name.endswith("_local_identity.mp4")]
    if not videos:
        videos = list(output.glob("*_local_identity.mp4"))
    if not videos:
        raise HTTPException(404, "Snapshot not available")
    cap = cv2.VideoCapture(str(videos[0]))
    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count > 1:
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(frame_count - 1, max(0, frame_count // 3)))
        ok, frame = cap.read()
        payload = overlay_frame(frame) if ok else None
    finally:
        cap.release()
    if not payload:
        raise HTTPException(404, "Snapshot frame not available")
    return Response(content=payload, media_type="image/jpeg", headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/api/jobs/{job_id}/media/snapshot.jpg")
def job_media_snapshot(job_id: str):
    return job_snapshot(job_id)


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return [x.public() for x in sorted(manager.jobs.values(), key=lambda j: j.created_at, reverse=True)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    return manager.get(job_id).public()


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str) -> dict[str, Any]:
    return manager.stop(job_id).public()


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict[str, Any]:
    previous = manager.get(job_id)
    if previous.status in {"QUEUED", "RUNNING", "CANCEL_REQUESTED"}:
        raise HTTPException(409, "An active job cannot be retried")
    request_data = manager._read_request(job_id)
    if request_data is None:
        raise HTTPException(409, "Original job request is missing or invalid")
    retry = manager.submit(
        f"Retry · {previous.name}", previous.source, previous.source_label,
        previous.source_kind, previous.preview_url, request_data["device"], request_data["gallery"],
        request_data["canonical_db"], request_data["extra_args"],
    )
    return retry.public()


@app.get("/api/jobs/{job_id}/artifacts/{artifact}")
def get_artifact(job_id: str, artifact: str):
    root = safe_job_path(job_id) / "output"
    if Path(artifact).name != artifact or (artifact not in ALLOWED_ARTIFACTS and not artifact.endswith("_identity.mp4")):
        raise HTTPException(404, "Artifact not available")
    path = root / artifact
    if not path.is_file():
        raise HTTPException(404, "Artifact not ready")
    return FileResponse(path)


@app.head("/api/jobs/{job_id}/artifacts/{artifact}")
def head_artifact(job_id: str, artifact: str):
    root = safe_job_path(job_id) / "output"
    if Path(artifact).name != artifact or (artifact not in ALLOWED_ARTIFACTS and not artifact.endswith("_identity.mp4")):
        raise HTTPException(404, "Artifact not available")
    path = root / artifact
    if not path.is_file():
        raise HTTPException(404, "Artifact not ready")
    return Response(headers={"content-type": "video/mp4" if path.suffix.lower() == ".mp4" else "application/octet-stream", "content-length": str(path.stat().st_size)})


@app.get("/api/jobs/{job_id}/summary")
def job_summary(job_id: str) -> dict[str, Any]:
    output = safe_job_path(job_id) / "output"
    summaries = read_json(output / "track_summaries.json", [])
    events = read_json(output / "identity_events.json", [])
    identities = sorted({x.get("person_id") for x in summaries if x.get("person_id")})
    states: dict[str, int] = {}
    for item in summaries:
        state = item.get("final_state", "UNKNOWN")
        states[state] = states.get(state, 0) + 1
    return {"identities": identities, "tracks": len(summaries), "events": len(events), "states": states,
            "recent_events": events[-30:]}


def identity_output(job_id: str) -> Path:
    return safe_job_path(job_id) / "output"


def identity_id_path(value: str) -> str:
    if not re.fullmatch(r"P\d{3,}", value):
        raise HTTPException(400, "Invalid identity id")
    return value


def memory_profile(job_id: str, person_id: str) -> dict[str, Any]:
    path = identity_output(job_id) / "person_memory.json"
    payload = read_json(path, {})
    profile = next((x for x in payload.get("profiles", []) if x.get("person_id") == person_id), None)
    if profile is None:
        raise HTTPException(404, "Identity not found")
    return profile


def memory_items(job_id: str, profile: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    items = []
    for item in profile.get(f"{kind}_memory", []):
        sample = str(item.get("sample_file", "")).replace("\\", "/")
        name = Path(sample).name
        items.append({**item, "image_url": f"/api/jobs/{job_id}/identities/{profile['person_id']}/images/{kind}/{name}"})
    return items


@app.get("/api/jobs/{job_id}/identities")
def job_identities(job_id: str) -> dict[str, Any]:
    output = identity_output(job_id)
    payload = read_json(output / "person_memory.json", {})
    raw_profiles = payload.get("profiles", [])
    if not raw_profiles:
        # Live workers persist per-person metadata before the final aggregate JSON.
        live_profiles: list[dict[str, Any]] = []
        for metadata_path in sorted((output / "person_memory").glob("P*/metadata.json")):
            metadata = read_json(metadata_path, None)
            if isinstance(metadata, dict) and metadata.get("person_id"):
                live_profiles.append({
                    **metadata,
                    "face_memory": metadata.get("face_samples", []),
                    "body_memory": metadata.get("body_samples", []),
                    "face_observations": len(metadata.get("face_samples", [])),
                    "body_observations": len(metadata.get("body_samples", [])),
                    "face_anchor_count": len(metadata.get("face_samples", [])),
                    "conflict_count": 0,
                })
        raw_profiles = live_profiles
    profiles = []
    npz_path = output / "person_memory_prototypes.npz"
    valid_face_vectors: set[str] = set()
    valid_body_vectors: set[str] = set()
    if npz_path.is_file():
        try:
            with np.load(npz_path, allow_pickle=False) as vectors:
                for k in vectors.files:
                    arr = vectors[k]
                    if arr.ndim == 1 and arr.shape[0] == 512 and not np.isnan(arr).any():
                        if "__face__" in k:
                            valid_face_vectors.add(k)
                        elif "__body__" in k:
                            valid_body_vectors.add(k)
        except (OSError, ValueError):
            valid_face_vectors = set()
            valid_body_vectors = set()
    for profile in raw_profiles:
        pid = profile.get("person_id")
        profiles.append({
            "person_id": pid, "employee_id": profile.get("employee_id"),
            "maturity": profile.get("maturity"), "confidence": profile.get("confidence", 0),
            "face_observations": profile.get("face_observations", 0),
            "body_observations": profile.get("body_observations", 0),
            "face_anchor_count": profile.get("face_anchor_count", 0),
            "conflict_count": profile.get("conflict_count", 0),
            "members": profile.get("members", []),
            "face_vectors": sum(key.startswith(f"{pid}__face__") for key in valid_face_vectors),
            "body_vectors": sum(key.startswith(f"{pid}__body__") for key in valid_body_vectors),
            "face_memory": memory_items(job_id, profile, "face"),
            "body_memory": memory_items(job_id, profile, "body"),
        })
    return {"job_id": job_id, "mode": payload.get("mode"), "profiles": profiles}


@app.get("/api/jobs/{job_id}/details")
def job_details(job_id: str) -> dict[str, Any]:
    output = identity_output(job_id)
    summary = job_summary(job_id)
    identities = job_identities(job_id)
    tracks = read_json(output / "track_summaries.json", [])
    events = read_json(output / "identity_events.json", [])
    database: dict[str, Any] = {"integrity": "not available", "tables": {}}
    tracklet_rows: list[dict[str, Any]] = []
    db_path = output / "identity.sqlite"
    if db_path.is_file():
        connection = None
        try:
            connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
            database["integrity"] = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            for table in ("tracklets", "detections", "observations", "assignments", "fusion_decisions", "identity_events"):
                database["tables"][table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            assignment_rows = connection.execute(
                "SELECT tracklet_id, state, reason, identity_id FROM assignments "
                "WHERE id IN (SELECT MAX(id) FROM assignments GROUP BY tracklet_id)"
            ).fetchall()
            latest_assignments = {int(row[0]): row[1:] for row in assignment_rows}
            for row in connection.execute(
                "SELECT id, camera, local_track_id, first_frame, last_frame FROM tracklets ORDER BY id"
            ).fetchall():
                tracklet_id, camera, local_track_id, first_frame, last_frame = row
                state, reason, identity_id = latest_assignments.get(tracklet_id, ("UNIDENTIFIED", "NO_ASSIGNMENT", None))
                face_obs, body_obs = connection.execute(
                    "SELECT "
                    "SUM(CASE WHEN kind = 'face' THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN kind = 'body' THEN 1 ELSE 0 END) "
                    "FROM observations WHERE tracklet_id = ?", (tracklet_id,)
                ).fetchone()
                tracklet_rows.append({
                    "tracklet_id": int(tracklet_id),
                    "camera": camera,
                    "track_id": int(local_track_id),
                    "person_id": f"I{int(identity_id):03d}" if identity_id is not None else None,
                    "bind_reason": reason or "NO_ASSIGNMENT",
                    "first_frame": int(first_frame),
                    "last_frame": int(last_frame),
                    "confirmed_employee": None,
                    "final_state": state or "UNIDENTIFIED",
                    "face_prototypes": [],
                    "body_prototypes": 0,
                    "online_face_observations": int(face_obs or 0),
                    "online_body_observations": int(body_obs or 0),
                    "ambiguous_frames": 0,
                    "strong_face_conflict": False,
                })
        except (OSError, sqlite3.Error) as exc:
            database["error"] = str(exc)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
    return {"job_id": job_id, "summary": summary, "identities": identities["profiles"],
            "tracks": tracks, "tracklets": tracklet_rows, "events": events, "database": database}


@app.get("/api/jobs/{job_id}/identities/{person_id}/images/{kind}/{filename}")
def identity_image(job_id: str, person_id: str, kind: str, filename: str):
    person_id = identity_id_path(person_id)
    if kind not in {"face", "body"} or Path(filename).name != filename:
        raise HTTPException(400, "Invalid identity image")
    path = identity_output(job_id) / "person_memory" / person_id / kind / filename
    if not path.is_file():
        raise HTTPException(404, "Identity crop not found")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/tracks")
def job_tracks(job_id: str, limit: int = 200) -> list[dict[str, Any]]:
    path = safe_job_path(job_id) / "output" / "tracks.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))[-max(1, min(limit, 1000)):]


@app.get("/api/jobs/{job_id}/log")
def job_log(job_id: str, tail: int = Query(default=1000, ge=1, le=5000), full: bool = False):
    path = safe_job_path(job_id) / "logs" / "worker.log"
    if not path.is_file():
        raise HTTPException(404, "Log not ready")
    if full:
        return StreamingResponse(path.open("rb"), media_type="text/plain")
    try:
        file_size = path.stat().st_size
        max_tail_bytes = 512 * 1024  # Read at most 512KB from the tail
        with path.open("rb") as f:
            if file_size > max_tail_bytes:
                f.seek(file_size - max_tail_bytes, os.SEEK_SET)
            chunk = f.read()
            text = chunk.decode("utf-8", errors="replace")
            lines = text.splitlines(keepends=True)
            if file_size > max_tail_bytes and len(lines) > 1:
                lines = lines[1:]  # Discard partial initial line
            tail_lines = lines[-max(1, min(tail, 5000)):]
            return Response(content="".join(tail_lines), media_type="text/plain")
    except OSError:
        raise HTTPException(500, "Failed to read log file")


@app.websocket("/ws/jobs/{job_id}")
async def job_socket(websocket: WebSocket, job_id: str) -> None:
    query_token = websocket.query_params.get("token") or websocket.query_params.get("ticket")
    auth_header = websocket.headers.get("Authorization") or websocket.headers.get("X-API-Key")
    cookie_token = websocket.cookies.get(COOKIE_NAME)
    if not verify_token(query_token, auth_header, cookie_token):
        await websocket.close(code=4401, reason="Unauthorized: invalid token")
        return
    try:
        job = manager.get(job_id)
    except HTTPException:
        await websocket.close(code=4404, reason="Job not found")
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(job.public())
            if job.status in {"COMPLETED", "FAILED", "STOPPED"}:
                break
            await asyncio.sleep(1)
            job = manager.get(job_id)
    except (WebSocketDisconnect, HTTPException):
        return


FRONTEND_DIST = ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
