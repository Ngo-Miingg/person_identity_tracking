from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np


def _norm(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32)
    return value / max(float(np.linalg.norm(value)), 1e-12)


def _center(box: np.ndarray) -> np.ndarray:
    return np.array(((float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0), dtype=np.float32)


def _height(box: np.ndarray) -> float:
    return max(float(box[3]) - float(box[1]), 1.0)


def _iou(left: np.ndarray, right: np.ndarray) -> float:
    x1, y1 = max(float(left[0]), float(right[0])), max(float(left[1]), float(right[1]))
    x2, y2 = min(float(left[2]), float(right[2])), min(float(left[3]), float(right[3]))
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_l = max(float(left[2]) - float(left[0]), 0.0) * max(float(left[3]) - float(left[1]), 0.0)
    area_r = max(float(right[2]) - float(right[0]), 0.0) * max(float(right[3]) - float(right[1]), 0.0)
    return inter / max(area_l + area_r - inter, 1e-6)


def _risk(left: np.ndarray, right: np.ndarray) -> bool:
    if _iou(left, right) >= 0.35:
        return True
    distance = float(np.linalg.norm(_center(left) - _center(right)))
    return distance / max((_height(left) + _height(right)) / 2.0, 1.0) < 0.35


def top3_median_similarity(clean: Iterable[np.ndarray], ephemeral: Iterable[np.ndarray]) -> float | None:
    scores = [float(_norm(old) @ _norm(new)) for old in clean for new in ephemeral]
    if not scores:
        return None
    return float(np.median(sorted(scores, reverse=True)[:3]))


@dataclass
class TrackObservation:
    track_id: int
    bbox: np.ndarray
    embedding: np.ndarray | None = None


@dataclass
class CleanSnapshot:
    observed_id: str
    track_id: int
    frame: int
    bbox: np.ndarray
    previous_center: np.ndarray | None = None
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float32))
    embeddings: list[np.ndarray] = field(default_factory=list)

    @property
    def center(self) -> np.ndarray:
        return _center(self.bbox)

    @property
    def direction(self) -> np.ndarray:
        return _norm(self.velocity) if float(np.linalg.norm(self.velocity)) > 1e-6 else np.zeros(2, dtype=np.float32)


@dataclass
class ShadowTrack:
    observed_id: str
    track_id: int
    last_frame: int
    bbox: np.ndarray
    previous_center: np.ndarray | None = None
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float32))
    post_frames: int = 0
    ephemeral: list[np.ndarray] = field(default_factory=list)

    @property
    def center(self) -> np.ndarray:
        return _center(self.bbox)


@dataclass
class _Event:
    event_id: str
    frame_start: int
    old: list[CleanSnapshot]
    candidates: dict[str, ShadowTrack] = field(default_factory=dict)
    separated_frames: int = 0
    logged: bool = False


class OcclusionRecoveryManager:
    """Shadow-only, event-level recovery proposals for raw tracker fragments."""

    def __init__(self, output_path: str | Path, *, min_post_frames: int = 3,
                 best_cost_gate: float = 0.45, recovery_margin: float = 0.25) -> None:
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.min_post_frames = int(min_post_frames)
        self.best_cost_gate = float(best_cost_gate)
        self.recovery_margin = float(recovery_margin)
        self._next_observed = 1
        self._next_event = 1
        self._next_raw: dict[int, str] = {}
        self._last_raw_frame: dict[int, int] = {}
        self._tracks: dict[str, ShadowTrack] = {}
        self._clean: dict[str, CleanSnapshot] = {}
        self._event: _Event | None = None
        self._crowded_active = False

    def _observed_id(self, track_id: int, frame: int) -> str:
        if track_id not in self._next_raw or frame - self._last_raw_frame.get(track_id, frame) > 1:
            self._next_raw[track_id] = f"O{self._next_observed:03d}"
            self._next_observed += 1
        self._last_raw_frame[track_id] = frame
        return self._next_raw[track_id]

    def step(self, frame: int, observations: Iterable[TrackObservation]) -> dict[int, str]:
        items = list(observations)
        ids = {item.track_id: self._observed_id(item.track_id, frame) for item in items}
        current: dict[str, ShadowTrack] = {}
        for item in items:
            oid = ids[item.track_id]
            previous = self._tracks.get(oid)
            center = _center(item.bbox)
            velocity = previous.velocity if previous is not None else np.zeros(2, dtype=np.float32)
            if previous is not None and frame > previous.last_frame:
                velocity = 0.7 * previous.velocity + 0.3 * (center - previous.previous_center)
            current[oid] = ShadowTrack(oid, item.track_id, frame, np.asarray(item.bbox, dtype=np.float32), center, velocity,
                                       previous.post_frames if previous else 0, list(previous.ephemeral) if previous else [])

        risky_pairs = [(left, right) for index, left in enumerate(items) for right in items[index + 1:] if _risk(left.bbox, right.bbox)]
        if not risky_pairs:
            self._crowded_active = False
        if self._event is None and len(risky_pairs) == 1 and len(items) == 2:
            old = []
            for item in items:
                oid = ids[item.track_id]
                old.append(self._clean.get(oid) or CleanSnapshot(oid, item.track_id, frame, item.bbox.copy()))
            self._event = _Event(f"E{self._next_event:04d}", frame, old)
            self._next_event += 1
        elif self._event is None and len(risky_pairs) > 0:
            if not self._crowded_active:
                self._emit(frame, [], [], eligible=False, decision="ABSTAIN", reason="more_than_two_tracks")
                self._crowded_active = True

        if self._event is not None:
            old_ids = {snapshot.observed_id for snapshot in self._event.old}
            if len(risky_pairs) == 0:
                self._event.separated_frames += 1
                for oid, track in current.items():
                    if oid not in old_ids:
                        self._event.candidates[oid] = track
            else:
                self._event.separated_frames = 0
            self._event.candidates = {oid: track for oid, track in current.items() if oid not in old_ids}
        else:
            # Only clean frames update the private shadow bank.
            if not risky_pairs:
                for oid, track in current.items():
                    snap = self._clean.get(oid)
                    if snap is None:
                        self._clean[oid] = CleanSnapshot(oid, track.track_id, frame, track.bbox.copy(), track.previous_center, track.velocity.copy())
                    else:
                        snap.previous_center, snap.bbox, snap.frame, snap.velocity = snap.center.copy(), track.bbox.copy(), frame, track.velocity.copy()

        self._tracks = current
        return ids

    def add_embedding(self, frame: int, track_id: int, embedding: np.ndarray) -> None:
        oid = self._next_raw.get(track_id)
        if oid is None:
            return
        embedding = _norm(embedding).astype(np.float32)
        if self._event is not None:
            old_ids = {snapshot.observed_id for snapshot in self._event.old}
            if oid in old_ids:
                return
            track = self._event.candidates.get(oid)
            if track is None:
                return
            track.ephemeral.append(embedding)
            track.post_frames += 1
            self._tracks[oid] = track
            if len(self._event.candidates) == 2 and self._event.separated_frames >= 1 and all(x.post_frames >= self.min_post_frames for x in self._event.candidates.values()):
                self._resolve(frame)
            return
        snap = self._clean.get(oid)
        if snap is not None and len(snap.embeddings) < 8:
            snap.embeddings.append(embedding)

    def _cost(self, old: CleanSnapshot, new: ShadowTrack) -> float | None:
        appearance = top3_median_similarity(old.embeddings, new.ephemeral)
        if appearance is None:
            return None
        gap = max(new.last_frame - old.frame, 1)
        predicted = old.center + old.velocity * gap
        motion = min(1.0, float(np.linalg.norm(predicted - new.center)) / max(2.0 * _height(old.bbox), 1.0))
        new_direction = _norm(new.velocity) if float(np.linalg.norm(new.velocity)) > 1e-6 else old.direction
        direction = (1.0 - float(old.direction @ new_direction)) / 2.0 if float(np.linalg.norm(old.direction)) else 0.5
        scale = min(1.0, abs(_height(old.bbox) - _height(new.bbox)) / max(_height(old.bbox), 1.0))
        return 0.20 * motion + 0.30 * direction + 0.40 * ((1.0 - appearance) / 2.0) + 0.10 * scale

    def _resolve(self, frame: int) -> None:
        assert self._event is not None
        candidates = list(self._event.candidates.values())
        costs = [[self._cost(old, new) for new in candidates] for old in self._event.old]
        if any(value is None for row in costs for value in row):
            self._emit(frame, candidates, costs, eligible=True, decision="ABSTAIN", reason="missing_clean_or_ephemeral_features")
            return
        h0 = float(costs[0][0] + costs[1][1])
        h1 = float(costs[0][1] + costs[1][0])
        best = min(h0, h1)
        decision = "LINK" if best <= self.best_cost_gate and abs(h0 - h1) >= self.recovery_margin else "ABSTAIN"
        links = [] if decision == "ABSTAIN" else (
            [[self._event.old[0].observed_id, candidates[0].observed_id], [self._event.old[1].observed_id, candidates[1].observed_id]] if h0 <= h1 else
            [[self._event.old[0].observed_id, candidates[1].observed_id], [self._event.old[1].observed_id, candidates[0].observed_id]])
        self._emit(frame, candidates, costs, eligible=True, decision=decision, h0=h0, h1=h1, best=best, links=links)

    def _emit(self, frame: int, candidates: list[ShadowTrack], costs: list[list[float | None]], *, eligible: bool, decision: str, reason: str | None = None,
              h0: float | None = None, h1: float | None = None, best: float | None = None, links: list[list[str]] | None = None) -> None:
        if self._event is None:
            event_id = f"E{self._next_event:04d}"
            self._next_event += 1
            payload = {"event_id": event_id, "frame_start": frame, "frame_decision": frame, "old_tracks": [], "new_tracks": [], "cost_matrix": [],
                       "h0_cost": None, "h1_cost": None, "delta": None, "best_cost": None, "appearance_stat": "top3_median",
                       "face_conflict": "UNAVAILABLE", "proposed_decision": decision, "proposed_links": [], "runtime_applied": False,
                       "eligible": False, "contaminated_shadow_updates": 0, "reason": reason}
            self._append(payload)
            return
        event = self._event
        payload = {"event_id": event.event_id, "frame_start": event.frame_start, "frame_decision": frame,
                   "old_tracks": [{"L": x.track_id, "O": x.observed_id} for x in event.old],
                   "new_tracks": [{"L": x.track_id, "O": x.observed_id} for x in candidates],
                   "cost_matrix": costs, "h0_cost": h0, "h1_cost": h1,
                   "delta": abs(h0 - h1) if h0 is not None and h1 is not None else None, "best_cost": best,
                   "appearance_stat": "top3_median", "face_conflict": "UNAVAILABLE", "proposed_decision": decision,
                   "proposed_links": links or [], "runtime_applied": False, "eligible": bool(eligible),
                   "contaminated_shadow_updates": 0, "reason": reason}
        self._append(payload)
        self._event = None

    def _append(self, payload: dict) -> None:
        with self.output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")

    def close(self, frame: int) -> None:
        if self._event is not None:
            self._emit(frame, list(self._event.candidates.values()), [], eligible=False, decision="ABSTAIN", reason="run_ended_before_recovery")
