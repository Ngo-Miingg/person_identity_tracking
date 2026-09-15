from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import numpy as np


@dataclass
class IdentityMetricSummary:
    total_tracks: int
    total_frames: int
    unbound_count: int
    confirmed_count: int
    conflict_count: int
    unique_persons: list[str]
    unique_employees: list[str]
    sqlite_integrity: str
    sqlite_table_counts: dict[str, int]
    npz_valid_512_vectors: int
    logical_violations: list[str]


class IdentityRunHarness:
    """Automated inspector for identity artifacts and integrity verification."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.tracks_csv_path = self.output_dir / "tracks.csv"
        self.sqlite_path = self.output_dir / "identity.sqlite"
        self.memory_json_path = self.output_dir / "person_memory.json"
        self.npz_path = self.output_dir / "person_memory_prototypes.npz"

    def read_tracks(self) -> list[dict[str, str]]:
        if not self.tracks_csv_path.is_file():
            return []
        with self.tracks_csv_path.open("r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def read_memory_json(self) -> dict[str, Any]:
        if not self.memory_json_path.is_file():
            return {}
        try:
            return json.loads(self.memory_json_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def read_sqlite_tables(self) -> dict[str, int]:
        if not self.sqlite_path.is_file():
            return {}
        counts = {}
        with sqlite3.connect(f"file:{self.sqlite_path.resolve().as_posix()}?mode=ro", uri=True) as conn:
            for tbl in ["tracklets", "detections", "observations", "assignments", "fusion_decisions", "identity_events"]:
                try:
                    c = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                    counts[tbl] = int(c)
                except Exception:
                    counts[tbl] = -1
        return counts

    def check_sqlite_logical_integrity(self) -> tuple[str, list[str]]:
        violations = []
        if not self.sqlite_path.is_file():
            return "MISSING_DB", ["identity.sqlite does not exist"]
        with sqlite3.connect(f"file:{self.sqlite_path.resolve().as_posix()}?mode=ro", uri=True) as conn:
            # 1. PRAGMA integrity_check
            pragma = conn.execute("PRAGMA integrity_check").fetchone()[0]

            # 2. Check for orphaned assignments pointing to non-existent tracklets
            orphaned_assignments = conn.execute("""
                SELECT COUNT(*) FROM assignments a
                LEFT JOIN tracklets t ON a.tracklet_id = t.id
                WHERE t.id IS NULL
            """).fetchone()[0]
            if orphaned_assignments > 0:
                violations.append(f"Found {orphaned_assignments} orphaned assignment records without valid tracklet.")

            # 3. Check for observations with negative quality or invalid dimensions
            invalid_obs = conn.execute("""
                SELECT COUNT(*) FROM observations
                WHERE quality < 0.0 OR quality > 1.05 OR dimension != 512
            """).fetchone()[0]
            if invalid_obs > 0:
                violations.append(f"Found {invalid_obs} observations with invalid quality or dimension.")

            # 4. Check for unpromoted body-only observations attempting to confirm an employee
            invalid_promotions = conn.execute("""
                SELECT COUNT(*) FROM fusion_decisions
                WHERE reason = 'BODY_ONLY_PROVISIONAL' AND state = 'CONFIRMED'
            """).fetchone()[0]
            if invalid_promotions > 0:
                violations.append(f"CRITICAL: Found {invalid_promotions} body-only fusion decisions illegally marked as CONFIRMED!")

        return str(pragma), violations

    def inspect_npz_vectors(self) -> tuple[int, int]:
        """Returns (valid_512_count, invalid_count)."""
        if not self.npz_path.is_file():
            return 0, 0
        valid = 0
        invalid = 0
        try:
            with np.load(self.npz_path, allow_pickle=False) as data:
                for k in data.files:
                    arr = data[k]
                    if arr.ndim == 1 and arr.shape[0] == 512 and not np.isnan(arr).any():
                        valid += 1
                    else:
                        invalid += 1
        except Exception:
            pass
        return valid, invalid

    def summarize(self) -> IdentityMetricSummary:
        tracks = self.read_tracks()
        pragma, violations = self.check_sqlite_logical_integrity()
        table_counts = self.read_sqlite_tables()
        valid_vecs, invalid_vecs = self.inspect_npz_vectors()
        if invalid_vecs > 0:
            violations.append(f"Found {invalid_vecs} invalid or non-512D arrays in prototype .npz archive.")

        unique_pids = sorted(list({t["person_id"] for t in tracks if t.get("person_id")}))
        unique_emps = sorted(list({t["identity"] for t in tracks if t.get("identity") and t["identity"].startswith("EMP")}))

        unbound = sum(1 for t in tracks if not t.get("person_id") or t["person_id"] in {"UNBOUND", ""})
        confirmed = sum(1 for t in tracks if t.get("identity_state") == "CONFIRMED")
        conflicts = sum(1 for t in tracks if t.get("identity_state") == "CONFLICT" or t.get("fusion_state") == "CONFLICT")

        return IdentityMetricSummary(
            total_tracks=len(tracks),
            total_frames=len(set(t["frame"] for t in tracks)) if tracks else 0,
            unbound_count=unbound,
            confirmed_count=confirmed,
            conflict_count=conflicts,
            unique_persons=unique_pids,
            unique_employees=unique_emps,
            sqlite_integrity=pragma,
            sqlite_table_counts=table_counts,
            npz_valid_512_vectors=valid_vecs,
            logical_violations=violations,
        )
