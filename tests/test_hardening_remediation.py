import os
import sys
import time
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import (
    issue_ticket, consume_ticket, verify_token,
    CrossProcessExecutionLock, _kill_process_tree, _get_process_create_time,
    _ensure_disk_safety, prune_storage
)
from src.person_memory import PersonMemory


class ComprehensiveHardeningRegressionSuite(unittest.TestCase):
    """Verifies all Phase 1 - 12 hardening remediations."""

    # -------------------------------------------------------------
    # 1. FINDING-01: Token & Short-Lived Ticket Security
    # -------------------------------------------------------------
    def test_short_lived_ticket_lifecycle(self):
        """Short-lived tickets must be valid before expiration and rejected after."""
        ticket = issue_ticket(scope="media", ttl_seconds=0.5)
        self.assertTrue(consume_ticket(ticket, required_scope="media"))
        time.sleep(0.6)
        self.assertFalse(consume_ticket(ticket, required_scope="media"))

    def test_cookie_authentication_verification(self):
        """HttpOnly cookie token verifies operator authentication without URL query."""
        from backend.app import API_KEY, COOKIE_NAME
        self.assertTrue(verify_token(token=None, auth_header=None, cookie_token=API_KEY))
        self.assertFalse(verify_token(token=None, auth_header=None, cookie_token="wrong-cookie-value"))

    # -------------------------------------------------------------
    # 2. FINDING-02: Multi-Worker Cross-Process Lock Safety
    # -------------------------------------------------------------
    def test_cross_process_lock_acquisition(self):
        """CrossProcessExecutionLock acquires and releases cleanly on Windows/Linux."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test_gpu.lock"
            lock1 = CrossProcessExecutionLock(lock_path)
            lock1.acquire()
            self.assertTrue(lock_path.is_file())
            lock1.release()

    # -------------------------------------------------------------
    # 3. FINDING-03: Storage Quota & Disk Safety
    # -------------------------------------------------------------
    def test_disk_safety_rejection(self):
        """_ensure_disk_safety raises HTTPException 507 when remaining disk space is insufficient."""
        from fastapi import HTTPException
        # Asking for an impossibly huge amount of disk space must trigger 507
        with self.assertRaises(HTTPException) as ctx:
            _ensure_disk_safety(required_bytes=1000 * 1024 * 1024 * 1024 * 1024)  # 1000 TB
        self.assertEqual(ctx.exception.status_code, 507)

    # -------------------------------------------------------------
    # 4. FINDING-04: PID Reuse Protection
    # -------------------------------------------------------------
    def test_pid_reuse_protection_blocks_kill(self):
        """_kill_process_tree must reject killing a process when expected_create_time does not match."""
        import psutil
        current_proc = psutil.Process(os.getpid())
        actual_create_time = current_proc.create_time()
        # Spoof a stale create_time from 1000 seconds ago
        stale_create_time = actual_create_time - 1000.0

        killed = _kill_process_tree(
            pid=os.getpid(),
            job_id="test-job",
            expected_create_time=stale_create_time
        )
        self.assertFalse(killed, "Violation: Process with mismatched create_time was targeted for kill!")

    # -------------------------------------------------------------
    # 5. FINDING-06: PersonMemory Profile Eviction & Bounds
    # -------------------------------------------------------------
    def test_person_memory_eviction_bounds(self):
        """Inactive anonymous profiles are evicted to prevent unbounded RAM growth."""
        with tempfile.TemporaryDirectory() as td:
            mem = PersonMemory(
                sample_root=td,
                max_active_anonymous_profiles=5,
                anonymous_profile_ttl_frames=100,
                require_face_before_person=False,
                new_person_after_frames=1,
            )
            # Create 10 inactive anonymous profiles at frame 10
            import numpy as np
            box = np.array([10.0, 10.0, 50.0, 50.0])
            for i in range(10):
                key = ("cam0", i + 1)
                mem.touch_track(key, frame=10, bbox=box)
                mem.maybe_seed_person(key, frame=10)

            self.assertGreater(len(mem.profiles), 5)
            # Advance to frame 300 (past TTL 100) and trigger eviction
            evicted = mem.evict_inactive_profiles(current_frame=300)
            self.assertGreater(evicted, 0)
            self.assertLessEqual(len(mem.profiles), 5)
            # Archived profiles retain history for audit payload
            payload = mem.payload()
            self.assertEqual(len(payload["profiles"]), 10)


if __name__ == "__main__":
    unittest.main()
