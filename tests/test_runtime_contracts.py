import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.app as backend


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class RuntimeContractTests(unittest.TestCase):
    def test_progress_fields_keep_stable_meanings(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs_root = Path(directory)
            output = jobs_root / "job1" / "output"
            (output / "live").mkdir(parents=True)
            (output / "tracks.csv").write_text("frame,track_id\n0,1\n0,2\n", encoding="utf-8")
            write_json(output / "live" / "telemetry.json", {"frame": 9})
            (output / "live" / "cam0.jpg").write_bytes(b"jpeg")
            job = backend.Job("job1", "test", "source", "source")
            with patch.object(backend, "JOBS_ROOT", jobs_root):
                progress = job.progress()
            self.assertEqual(progress["rows"], 2)
            self.assertEqual(progress["frames"], 10)
            self.assertEqual(progress["live_images"], 1)

    def test_completed_progress_uses_last_recorded_frame_without_live_telemetry(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs_root = Path(directory)
            output = jobs_root / "job1" / "output"
            output.mkdir(parents=True)
            (output / "tracks.csv").write_text("frame,track_id\n2,1\n8,1\n", encoding="utf-8")
            job = backend.Job("job1", "test", "source", "source", status="COMPLETED")
            with patch.object(backend, "JOBS_ROOT", jobs_root):
                progress = job.progress()
            self.assertEqual(progress["rows"], 2)
            self.assertEqual(progress["frames"], 9)

    def test_progress_reuses_cache_when_artifacts_are_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs_root = Path(directory)
            output = jobs_root / "job1" / "output"
            output.mkdir(parents=True)
            (output / "tracks.csv").write_text("frame,track_id\n8,1\n", encoding="utf-8")
            job = backend.Job("job1", "test", "source", "source", status="COMPLETED")
            with patch.object(backend, "JOBS_ROOT", jobs_root):
                with patch.object(Path, "open", wraps=Path.open) as open_mock:
                    first = job.progress()
                    second = job.progress()
            self.assertEqual(first, second)
            self.assertEqual(open_mock.call_count, 1)

    def test_artifact_validator_rejects_missing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            error = backend.validate_completed_artifacts(Path(directory), "upload")
        self.assertIn("required artifacts are missing", error or "")

    def test_artifact_validator_rejects_sqlite_without_identity_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "tracks.csv").write_text("", encoding="utf-8")
            for name in ("identity_events.json", "track_summaries.json"):
                write_json(output / name, [])
            write_json(output / "person_memory.json", {"profiles": []})
            for name in ("face_prototypes.npz", "body_prototypes.npz", "person_memory_prototypes.npz"):
                np.savez_compressed(output / name)
            connection = sqlite3.connect(output / "identity.sqlite")
            try:
                connection.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY)")
                connection.commit()
            finally:
                connection.close()
            error = backend.validate_completed_artifacts(output, "rtsp")
            self.assertIn("schema is incomplete", error or "")

    def test_restart_normalizes_interrupted_jobs_and_recovers_valid_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs_root = Path(directory)
            records = {
                "running": {"status": "RUNNING", "pid": 101, "process_create_time": 1.0},
                "cancelled": {"status": "CANCEL_REQUESTED", "pid": 102, "process_create_time": 2.0},
                "queued": {"status": "QUEUED"},
                "broken": {"status": "QUEUED"},
            }
            for index, (job_id, values) in enumerate(records.items()):
                root = jobs_root / job_id
                root.mkdir()
                write_json(root / "status.json", {
                    "id": job_id, "name": job_id, "source": "input.mp4", "source_label": "input",
                    "created_at": float(index), **values,
                })
            write_json(jobs_root / "queued" / "request.json", {
                "device": "cpu", "gallery": "gallery", "canonical_db": "people.db", "extra_args": ["--flag"],
            })

            manager = backend.JobManager.__new__(backend.JobManager)
            manager.jobs = {}
            manager.lock = threading.RLock()
            manager._start_thread = Mock()
            with patch.object(backend, "JOBS_ROOT", jobs_root), patch.object(backend, "_kill_process_tree") as kill:
                manager._load_existing()

            self.assertEqual(manager.jobs["running"].status, "FAILED")
            self.assertEqual(manager.jobs["cancelled"].status, "STOPPED")
            self.assertIsNone(manager.jobs["running"].pid)
            self.assertEqual(manager.jobs["broken"].status, "FAILED")
            manager._start_thread.assert_called_once()
            recovered_job, request = manager._start_thread.call_args.args
            self.assertEqual(recovered_job.id, "queued")
            self.assertEqual(request, {
                "device": "cpu", "gallery": "gallery", "canonical_db": "people.db", "extra_args": ["--flag"],
            })
            self.assertEqual(kill.call_count, 2)

    def test_zero_exit_with_invalid_artifacts_is_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs_root = Path(directory)
            root = jobs_root / "job1"
            (root / "logs").mkdir(parents=True)
            (root / "output").mkdir()
            job = backend.Job("job1", "test", "input.mp4", "input", source_kind="upload")
            manager = backend.JobManager.__new__(backend.JobManager)
            manager.lock = threading.RLock()
            manager.execution_lock = Mock()
            process = Mock(pid=1234)
            process.wait.return_value = 0

            with (
                patch.object(backend, "JOBS_ROOT", jobs_root),
                patch.object(backend.subprocess, "Popen", return_value=process),
                patch.object(backend, "_get_process_create_time", return_value=10.0),
                patch.object(backend, "validate_completed_artifacts", return_value="missing final MP4"),
            ):
                manager._run(job, "cpu", None, None, [])

            self.assertEqual(job.status, "FAILED")
            self.assertEqual(job.error, "missing final MP4")
            self.assertEqual(job.return_code, 0)
            self.assertIsNone(job.pid)
            manager.execution_lock.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
