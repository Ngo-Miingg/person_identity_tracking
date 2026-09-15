from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path
import json
import math

import cv2
import numpy as np

from .models import TrackKey
from .prototypes import normalize
from .anonymous_face_recognizer import AnonymousFaceRecognizer, FaceRankResult


TRUSTED_FACE_TIERS = {"support", "strong"}


@dataclass
class BodyAssociationDecision:
    """Auditable tri-state decision for one O-to-profile body evaluation."""

    state: str
    candidate_person_id: int | None = None
    body_score: float | None = None
    body_centroid_score: float | None = None
    body_robust_score: float | None = None
    motion_score: float | None = None
    combined_score: float | None = None
    runner_up_person_id: int | None = None
    runner_up_score: float | None = None
    margin: float | None = None
    sample_count: int = 0
    self_consistency: float | None = None
    reason: str = ""

    @property
    def decision(self) -> str:
        return self.state

    def __iter__(self):
        # Keep existing callers source-compatible while exposing the tri-state result.
        yield self
        yield None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            aliases = {
                "BLOCK_FACE_CONFLICT": "FACE_CONFLICT",
                "HOLD_AMBIGUOUS_NEW_G": "AMBIGUOUS_MARGIN",
            }
            return self.state == other or self.reason == aliases.get(other)
        return super().__eq__(other)

    def as_dict(self) -> dict:
        return {
            "decision": self.state,
            "candidate_person_id": self.candidate_person_id,
            "body_score": self.body_score,
            "body_centroid_score": self.body_centroid_score,
            "body_robust_score": self.body_robust_score,
            "motion_score": self.motion_score,
            "combined_score": self.combined_score,
            "runner_up_person_id": self.runner_up_person_id,
            "runner_up_score": self.runner_up_score,
            "margin": self.margin,
            "sample_count": self.sample_count,
            "self_consistency": self.self_consistency,
            "reason": self.reason,
        }


class TrackInstanceManager:
    """Maps raw tracker IDs to lifecycle-bound immutable instance IDs (Oxxx).

    If a raw tracker ID disappears for longer than max_gap frames and returns,
    it is assigned a brand-new instance ID and starts completely UNBOUND.
    """

    def __init__(self, max_gap: int = 60) -> None:
        self.max_gap = int(max_gap)
        self._next_instance: int = 1
        self._active_instances: dict[tuple[str, int], int] = {}
        self._last_seen: dict[tuple[str, int], int] = {}
        self._closed_instances: set[int] = set()

    def get_or_create(self, raw_tid: int, frame: int, camera: str = "default") -> tuple[int, bool]:
        """Returns (instance_id, is_new)."""
        raw_key = (str(camera), int(raw_tid))
        last = self._last_seen.get(raw_key)
        is_new = False
        if last is None or (int(frame) - last) > self.max_gap or raw_key not in self._active_instances:
            old_instance = self._active_instances.get(raw_key)
            if old_instance is not None:
                self._closed_instances.add(old_instance)
            instance_id = self._next_instance
            self._next_instance += 1
            self._active_instances[raw_key] = instance_id
            is_new = True
        self._last_seen[raw_key] = int(frame)
        return self._active_instances[raw_key], is_new

    def get(self, raw_tid: int, camera: str = "default") -> int | None:
        return self._active_instances.get((str(camera), int(raw_tid)))

    def object_label(self, raw_tid: int, camera: str = "default") -> str:
        inst = self.get(raw_tid, camera)
        return f"O{inst:03d}" if inst is not None else "O:---"

    def mark_ended(self, raw_tid: int, camera: str = "default") -> int | None:
        raw_key = (str(camera), int(raw_tid))
        self._last_seen.pop(raw_key, None)
        instance_id = self._active_instances.pop(raw_key, None)
        if instance_id is not None:
            self._closed_instances.add(instance_id)
        return instance_id

    def is_closed(self, instance_id: int) -> bool:
        return int(instance_id) in self._closed_instances

    def expire(self, frame: int, camera: str | None = None) -> list[tuple[str, int, int]]:
        """Close raw mappings that have exceeded the configured lifecycle gap."""
        ended: list[tuple[str, int, int]] = []
        for raw_key, last in list(self._last_seen.items()):
            if camera is not None and raw_key[0] != str(camera):
                continue
            if int(frame) - last <= self.max_gap:
                continue
            instance_id = self._active_instances.pop(raw_key, None)
            self._last_seen.pop(raw_key, None)
            if instance_id is not None:
                self._closed_instances.add(instance_id)
                ended.append((raw_key[0], raw_key[1], instance_id))
        return ended


@dataclass
class FaceMemoryItem:
    embedding: np.ndarray
    quality: float
    pose: str
    tier: str
    support: int = 1
    core: bool = False
    first_frame: int = 0
    last_frame: int = 0
    sample_file: str | None = None


@dataclass
class BodyMemoryItem:
    embedding: np.ndarray
    quality: float
    support: int = 1
    core: bool = False
    first_frame: int = 0
    last_frame: int = 0
    sample_file: str | None = None


@dataclass
class TrackSegment:
    start_frame: int
    end_frame: int | None
    person_id: int | None
    reason: str
    authority: str


@dataclass
class FaceAuthorityResult:
    frame: int
    person_id: int | None
    decision: str
    accepted: bool
    top1_person_id: int | None = None
    top1_score: float | None = None
    top2_person_id: int | None = None
    top2_score: float | None = None
    margin: float | None = None
    candidate_votes: int = 0
    candidate_needed: int = 0
    pose: str = ""
    tier: str = ""
    quality: float = 0.0

    def row_fields(self) -> dict:
        return {
            "face_id_frame": self.frame,
            "face_id_person": f"P{self.person_id:03d}" if self.person_id is not None else "",
            "face_id_decision": self.decision,
            "face_id_accepted": self.accepted,
            "face_id_top1": f"P{self.top1_person_id:03d}" if self.top1_person_id is not None else "",
            "face_id_top1_score": self.top1_score if self.top1_score is not None else "",
            "face_id_top2": f"P{self.top2_person_id:03d}" if self.top2_person_id is not None else "",
            "face_id_top2_score": self.top2_score if self.top2_score is not None else "",
            "face_id_margin": self.margin if self.margin is not None else "",
            "face_id_candidate_votes": self.candidate_votes,
            "face_id_candidate_needed": self.candidate_needed,
            "face_id_pose": self.pose,
            "face_id_tier": self.tier,
            "face_id_quality": self.quality,
        }


@dataclass
class TrackBinding:
    key: TrackKey
    first_frame: int
    last_frame: int
    person_id: int | None = None
    bind_reason: str | None = None
    safe_after_frame: int = -1
    ambiguous_frames: int = 0
    face_observations: int = 0
    body_observations: int = 0
    last_bbox: np.ndarray | None = None
    prev_bbox: np.ndarray | None = None
    prev_bbox_frame: int | None = None
    last_body: np.ndarray | None = None
    last_body_frame: int | None = None
    appearance_jump_until: int = -1
    strong_face_conflict: bool = False
    body_quarantined: bool = False
    learning_frozen: bool = False
    frozen_since_frame: int | None = None
    frozen_face_confirmations: int = 0
    current_face_confirmations: int = 0
    face_evidence_count: int = 0
    current_face_view_candidate: np.ndarray | None = None
    current_face_view_pose: str = ""
    current_face_view_last_frame: int = -1
    current_face_view_samples: list[dict] = field(default_factory=list)
    pending_body_samples: list[dict] = field(default_factory=list)
    body_promotion_state: str = "PENDING"
    body_promoted_count: int = 0
    body_quarantine_reason: str | None = None
    last_body_decision: BodyAssociationDecision | None = None
    segments: list[TrackSegment] = field(default_factory=list)
    face_candidate_pid: int | None = None
    face_candidate_votes: int = 0
    face_candidate_last_frame: int = -1
    new_face_candidate: np.ndarray | None = None
    new_face_votes: int = 0
    new_face_last_frame: int = -1
    body_candidate_pid: int | None = None
    body_candidate_votes: int = 0
    body_candidate_last_frame: int = -1
    identity_change_until: int = -1
    identity_change_count: int = 0

    @property
    def age(self) -> int:
        return max(int(self.last_frame) - int(self.first_frame) + 1, 1)


@dataclass
class PersonProfile:
    person_id: int
    employee_id: str | None = None
    members: list[TrackKey] = field(default_factory=list)
    face_bank: list[FaceMemoryItem] = field(default_factory=list)
    body_bank: list[BodyMemoryItem] = field(default_factory=list)
    last_seen: dict[str, int] = field(default_factory=dict)
    last_bbox: dict[str, np.ndarray] = field(default_factory=dict)
    prev_bbox: dict[str, np.ndarray] = field(default_factory=dict)
    prev_bbox_frame: dict[str, int] = field(default_factory=dict)
    face_anchor_count: int = 0
    body_observations: int = 0
    face_observations: int = 0
    reacquire_count: int = 0
    conflict_count: int = 0
    recent_face_embedding: np.ndarray | None = None
    recent_face_quality: float = 0.0
    recent_face_pose: str = ""
    recent_face_frame: int = -1
    recent_face_camera: str = ""

    def face_core(self) -> list[FaceMemoryItem]:
        core = [x for x in self.face_bank if x.tier in TRUSTED_FACE_TIERS and x.core]
        if core:
            return core
        trusted = [x for x in self.face_bank if x.tier in TRUSTED_FACE_TIERS]
        repeated = [x for x in trusted if x.support >= 2]
        return repeated if repeated else trusted

    def body_core(self) -> list[BodyMemoryItem]:
        core = [x for x in self.body_bank if x.core]
        return core if core else self.body_bank

    def maturity(self) -> str:
        face = len(self.face_core())
        body = len(self.body_core())
        members = len(self.members)
        if self.employee_id:
            return "CONFIRMED"
        has_frontal_face = any(item.pose == "front" for item in self.face_core())
        if self.face_anchor_count >= 2 and body >= 3 and has_frontal_face:
            return "STABLE"
        if face >= 1 or body >= 2 or members >= 2:
            return "LEARNING"
        return "NEW"

    def confidence(self) -> float:
        face = min(len(self.face_core()) / 3.0, 1.0)
        body = min(len(self.body_core()) / 5.0, 1.0)
        members = min(len(self.members) / 3.0, 1.0)
        reacq = min(self.reacquire_count / 2.0, 1.0)
        emp = 1.0 if self.employee_id else 0.0
        return float(np.clip(0.34 * face + 0.24 * body + 0.16 * members + 0.16 * reacq + 0.10 * emp, 0.0, 1.0))


@dataclass
class PersonDecision:
    frame: int
    camera: str
    track_id: int
    person_id: int | None
    reason: str
    accepted: bool
    score: float | None = None
    margin: float | None = None
    face_score: float | None = None
    body_score: float | None = None
    motion_score: float | None = None


class RepresentativeStore:
    """Stores only representative face/person crops for demo and later enrollment.

    Files are intentionally small in count. Memory embeddings remain the source of
    matching truth; JPGs are human-inspectable examples for FACE/PERSON profiles.
    """

    def __init__(self, root: str | Path, face_per_pose: int = 3, body_slots: int = 8) -> None:
        self.root = Path(root)
        self.face_per_pose = max(int(face_per_pose), 1)
        self.body_slots = max(int(body_slots), 1)
        self.root.mkdir(parents=True, exist_ok=True)

    def _person_dir(self, pid: int) -> Path:
        p = self.root / f"P{pid:03d}"
        (p / "face").mkdir(parents=True, exist_ok=True)
        (p / "body").mkdir(parents=True, exist_ok=True)
        return p

    def save_face(self, pid: int, pose: str, slot: int, image: np.ndarray) -> str | None:
        if image is None or image.size == 0:
            return None
        p = self._person_dir(pid) / "face" / f"{pose}_{slot + 1:02d}.jpg"
        if cv2.imwrite(str(p), image):
            return str(p.relative_to(self.root.parent))
        return None

    def save_face_evidence(
        self, camera: str, instance_id: int, frame: int, pose: str, image: np.ndarray,
    ) -> str | None:
        """Save usable face observations separately from identity prototypes."""
        if image is None or image.size == 0:
            return None
        safe_camera = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(camera))
        folder = self.root / "_face_evidence" / safe_camera / f"O{int(instance_id):03d}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{int(frame):08d}_{pose}.jpg"
        return str(path) if cv2.imwrite(str(path), image) else None

    def save_body(self, pid: int, slot: int, image: np.ndarray) -> str | None:
        if image is None or image.size == 0:
            return None
        p = self._person_dir(pid) / "body" / f"view_{slot + 1:02d}.jpg"
        if cv2.imwrite(str(p), image):
            return str(p.relative_to(self.root.parent))
        return None

    def write_metadata(self, profile: PersonProfile) -> None:
        p = self._person_dir(profile.person_id) / "metadata.json"
        payload = {
            "person_id": f"P{profile.person_id:03d}",
            "employee_id": profile.employee_id,
            "maturity": profile.maturity(),
            "confidence": profile.confidence(),
            "members": [{"camera": c, "track_id": int(t)} for c, t in profile.members],
            "face_samples": [
                {
                    "pose": x.pose,
                    "tier": x.tier,
                    "quality": x.quality,
                    "support": x.support,
                    "core": x.core,
                    "sample_file": x.sample_file,
                }
                for x in profile.face_bank
            ],
            "body_samples": [
                {
                    "quality": x.quality,
                    "support": x.support,
                    "core": x.core,
                    "sample_file": x.sample_file,
                }
                for x in profile.body_bank
            ],
        }
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class PersonMemory:
    """Face-first person memory.

    Invariants:
      1. Body/motion can never move an already-bound local track to another P.
         Trusted face authority may split the track into a new P segment without
         rewriting earlier history.
      2. Brief local-track breaks are handled by a recent-person lease first
         (motion/geometry, optionally body). No global body search is performed.
      3. Trusted face evidence is the only biometric cue allowed to identify a
         person across long gaps or to confirm EMPxxx.
      4. Body embeddings are learned as same-session appearance and are used only
         for short-gap continuity; they do not define permanent identity.
      5. Ambiguous/crossing frames pause learning to reduce memory contamination.
    """

    def __init__(
        self,
        *,
        sample_root: str | Path,
        short_gap_frames: int = 45,
        motion_only_gap_frames: int = 6,
        new_person_after_frames: int = 12,
        ambiguity_grace_frames: int = 8,
        face_match_threshold: float = 0.56,
        face_match_margin: float = 0.04,
        face_view_update_threshold: float = 0.58,
        face_learn_quality: float = 0.32,
        face_match_confirmations: int = 2,
        face_new_confirmations: int = 2,
        face_candidate_max_gap: int = 16,
        face_recent_anchor_frames: int = 300,
        body_short_gap_near: float = 0.76,
        body_short_gap_far: float = 0.84,
        body_match_margin: float = 0.05,
        body_learn_quality: float = 0.35,
        body_novelty_threshold: float = 0.91,
        body_jump_threshold: float = 0.48,
        max_face_per_pose: int = 12,
        max_body_views: int = 8,
        require_face_before_person: bool = True,
        max_active_anonymous_profiles: int = 200,
        anonymous_profile_ttl_frames: int = 1500,
    ) -> None:
        self.short_gap_frames = max(int(short_gap_frames), 1)
        self.motion_only_gap_frames = max(int(motion_only_gap_frames), 1)
        self.new_person_after_frames = max(int(new_person_after_frames), 1)
        self.ambiguity_grace_frames = max(int(ambiguity_grace_frames), 0)
        self.face_match_threshold = float(face_match_threshold)
        self.face_match_margin = float(face_match_margin)
        self.face_view_update_threshold = float(face_view_update_threshold)
        self.face_learn_quality = float(face_learn_quality)
        self.face_match_confirmations = max(int(face_match_confirmations), 1)
        self.face_new_confirmations = max(int(face_new_confirmations), 1)
        self.face_candidate_max_gap = max(int(face_candidate_max_gap), 1)
        self.face_recent_anchor_frames = max(int(face_recent_anchor_frames), 1)
        self.face_recognizer = AnonymousFaceRecognizer(self.face_match_threshold, self.face_match_margin)
        self.body_short_gap_near = float(body_short_gap_near)
        self.body_short_gap_far = float(body_short_gap_far)
        self.body_match_margin = float(body_match_margin)
        self.body_learn_quality = float(body_learn_quality)
        self.body_novelty_threshold = float(body_novelty_threshold)
        self.body_jump_threshold = float(body_jump_threshold)
        self.max_face_per_pose = max(int(max_face_per_pose), 1)
        self.max_body_views = max(int(max_body_views), 1)
        self.require_face_before_person = bool(require_face_before_person)
        self.max_active_anonymous_profiles = max(int(max_active_anonymous_profiles), 10)
        self.anonymous_profile_ttl_frames = max(int(anonymous_profile_ttl_frames), 100)

        self.profiles: dict[int, PersonProfile] = {}
        self.archived_profiles: dict[int, PersonProfile] = {}
        self.tracks: dict[TrackKey, TrackBinding] = {}
        self.decisions: list[PersonDecision] = []
        self.events: list[dict] = []
        self.body_decision_events: list[dict] = []
        self._next_person_id = 1
        self.store = RepresentativeStore(sample_root, face_per_pose=max_face_per_pose, body_slots=max_body_views)
        self._face_diagnostics: dict[TrackKey, FaceAuthorityResult] = {}

    def evict_inactive_profiles(self, current_frame: int) -> int:
        """Evicts stale anonymous profiles with no active tracks from active RAM search set."""
        active_pids = {st.person_id for st in self.tracks.values() if st.person_id is not None and (int(current_frame) - st.last_frame) <= self.short_gap_frames}
        evicted = 0

        # Check profiles eligible for eviction
        candidates = []
        for pid, p in list(self.profiles.items()):
            # Never evict confirmed employees
            if p.employee_id:
                continue
            # Never evict profile of an actively observed track
            if pid in active_pids:
                continue
            last_seen_frame = max(p.last_seen.values()) if p.last_seen else -1
            age_inactive = int(current_frame) - last_seen_frame
            # Evict if inactive for longer than TTL frames or if profile capacity exceeded
            if age_inactive > self.anonymous_profile_ttl_frames or len(self.profiles) > self.max_active_anonymous_profiles:
                candidates.append((age_inactive, pid))

        # Sort most inactive first
        candidates.sort(reverse=True, key=lambda x: x[0])
        for _, pid in candidates:
            if len(self.profiles) <= self.max_active_anonymous_profiles and _ < self.anonymous_profile_ttl_frames:
                break
            p = self.profiles.pop(pid, None)
            if p is not None:
                self.archived_profiles[pid] = p
                evicted += 1

        return evicted

    def freeze_missing_tracks(self, camera: str, frame: int, active_instance_ids: set[int]) -> None:
        """Stop biometric learning as soon as an O disappears from a frame."""
        for key, st in self.tracks.items():
            if key[0] != str(camera) or st.person_id is None:
                continue
            if key[1] in active_instance_ids or st.last_frame >= int(frame):
                continue
            if not st.learning_frozen:
                st.learning_frozen = True
                st.frozen_since_frame = int(frame)
                st.frozen_face_confirmations = 0
                st.pending_body_samples.clear()
                st.current_face_view_candidate = None
                st.current_face_view_samples = []
                st.body_promotion_state = "FROZEN_TRACK_GAP"

    # ------------------------------ public views ------------------------------
    def profile_for_track(self, key: TrackKey) -> PersonProfile | None:
        st = self.tracks.get(key)
        return self.profiles.get(st.person_id) if st and st.person_id is not None else None

    def state_for_track(self, key: TrackKey) -> TrackBinding | None:
        return self.tracks.get(key)

    def public_label(self, key: TrackKey) -> str:
        st = self.tracks.get(key)
        if st is None or st.person_id is None:
            return "P:---"
        return f"P:{st.person_id:03d}"

    def mapping(self) -> dict[TrackKey, int]:
        return {k: st.person_id for k, st in self.tracks.items() if st.person_id is not None}

    def face_diagnostic(self, key: TrackKey) -> FaceAuthorityResult | None:
        return self._face_diagnostics.get(key)

    def import_embedding_records(self, records: list[object]) -> None:
        """Restore reusable P profiles from a previous embedding store."""
        grouped: dict[int, list[object]] = defaultdict(list)
        for record in records:
            pid = getattr(record, "person_id", None)
            if pid is not None:
                grouped[int(pid)].append(record)
        for pid, items in grouped.items():
            profile = self.profiles.setdefault(pid, PersonProfile(pid))
            for item in items:
                kind = getattr(item, "kind", "")
                emb = normalize(np.asarray(item.embedding, dtype=np.float32))
                quality = float(getattr(item, "quality", 0.0))
                frame = int(getattr(item, "frame", 0))
                if kind == "face" and quality >= self.face_learn_quality:
                    self._add_face(profile, emb, quality, getattr(item, "pose", "front"), "support", frame)
                elif kind == "body" and quality >= self.body_learn_quality:
                    self._add_body(profile, emb, quality, frame)
            profile.face_anchor_count = sum(1 for x in profile.face_bank if x.tier in TRUSTED_FACE_TIERS)
        if self.profiles:
            self._next_person_id = max(self.profiles) + 1

    def reconcile_track_faces(self, key: TrackKey, observations: list[object]) -> int | None:
        """Re-evaluate a completed local track against all known face profiles.

        Online binding is provisional. This pass uses independent observations
        collected across the tracklet and may create a new segment when another
        profile wins consistently. Raw observations are never rewritten.
        """
        st = self.tracks.get(key)
        if st is None or not observations:
            return st.person_id if st is not None else None
        usable = [x for x in observations if getattr(x, "kind", "") == "face" and float(getattr(x, "quality", 0.0)) >= self.face_learn_quality]
        if len(usable) < 2:
            return st.person_id

        if len(self.profiles) < 2:
            return st.person_id

        votes: dict[int, list[float]] = defaultdict(list)
        current_pid = st.person_id
        for obs in usable:
            query = normalize(np.asarray(obs.embedding, dtype=np.float32))
            ranked: list[tuple[float, int]] = []
            for pid, profile in self.profiles.items():
                # Never let a provisional profile win against itself. A new
                # track must first be compared with existing profiles before
                # its own observations are promoted into a new anchor.
                if pid == current_pid and not profile.face_core():
                    continue
                vectors = self._face_bank_vectors(profile, key[0], int(obs.frame))
                if not vectors:
                    continue
                ranked.append((max(float(query @ normalize(v)) for v in vectors), pid))
            ranked.sort(reverse=True)
            if not ranked:
                continue
            best_score, best_pid = ranked[0]
            second = ranked[1][0] if len(ranked) > 1 else -1.0
            if best_score >= self.face_match_threshold and best_score - second >= self.face_match_margin:
                votes[best_pid].append(best_score)

        if not votes:
            # No prior identity matched. Now it is safe to promote this
            # provisional track's mutually consistent observations.
            if current_pid is not None:
                current = self.profiles[current_pid]
                if not current.face_core():
                    ranked = sorted(usable, key=lambda x: float(x.quality), reverse=True)
                    first = normalize(np.asarray(ranked[0].embedding, dtype=np.float32))
                    agreeing = [x for x in ranked[1:] if float(first @ normalize(x.embedding)) >= 0.72]
                    if agreeing:
                        self._learn_face_sample(
                            current, key, int(ranked[0].frame), first,
                            float(ranked[0].quality), getattr(ranked[0], "pose", "front"),
                            "support", None,
                        )
                        if st.segments and st.segments[-1].person_id == current.person_id:
                            st.segments[-1].authority = "face"
                            st.segments[-1].reason = "offline_face_reconciliation"
                            st.bind_reason = "offline_face_reconciliation"
                            self.promote_body_if_authorized(
                                key, int(ranked[0].frame), "FACE_CONFIRMED",
                            )
            return st.person_id
        target_pid, scores = max(votes.items(), key=lambda item: (len(item[1]), sum(item[1]) / len(item[1])))
        mean_score = sum(scores) / len(scores)
        if target_pid == st.person_id or len(scores) < 2:
            return st.person_id
        if mean_score < self.face_match_threshold or len(scores) / len(usable) < 0.5:
            return st.person_id
        target = self.profiles[target_pid]
        start = int(min(getattr(x, "frame", st.first_frame) for x in usable if target_pid in votes))
        self.replace_track_identity(st, target, "offline_face_reconciliation", score=mean_score, frame=start)
        self.events.append({
            "frame": start, "camera": key[0], "track_id": key[1],
            "event": "offline_face_reconciled", "person_id": target_pid,
            "score": mean_score, "votes": len(scores),
        })
        return target_pid

    def backfill_track_observations(
        self, key: TrackKey, face_observations: list[object], body_embeddings: list[np.ndarray],
    ) -> None:
        """Recover pre-bind evidence without importing a tracker switch."""
        st = self.tracks.get(key)
        if st is None or st.person_id is None:
            return
        target = self.profiles[st.person_id]
        target_faces = target.face_core()
        accepted_frames: set[int] = set()
        for observation in face_observations:
            quality = float(getattr(observation, "quality", 0.0))
            if quality < self.face_learn_quality:
                continue
            embedding = normalize(np.asarray(observation.embedding, dtype=np.float32))
            target_score = max((float(embedding @ normalize(item.embedding)) for item in target_faces), default=0.0)
            other_score = max(
                (float(embedding @ normalize(item.embedding))
                 for pid, profile in self.profiles.items() if pid != target.person_id
                 for item in profile.face_core()),
                default=-1.0,
            )
            if target_faces and (target_score < 0.65 or target_score < other_score + 0.03):
                continue
            self._learn_face_sample(
                target, key, int(getattr(observation, "frame", st.first_frame)), embedding,
                quality, getattr(observation, "pose", "front"), getattr(observation, "tier", "support"),
                getattr(st, "face_crops", {}).get(int(getattr(observation, "frame", st.first_frame))),
            )
            accepted_frames.add(int(getattr(observation, "frame", st.first_frame)))
            target_faces = target.face_core()
        # Body vectors have no frame metadata here. If face observations are
        # mixed or rejected, importing them would attach evidence from an
        # unknown frame to the newly bound identity.
        if face_observations:
            return
        for raw in body_embeddings:
            embedding = normalize(np.asarray(raw, dtype=np.float32))
            target_score = self._best_body_score(embedding, target) or 0.0
            other_score = max(
                (self._best_body_score(embedding, profile) or 0.0
                 for pid, profile in self.profiles.items() if pid != target.person_id),
                default=0.0,
            )
            if other_score >= self.body_short_gap_far and other_score > target_score + self.body_match_margin:
                continue
            self._add_body(target, embedding, self.body_learn_quality, st.last_frame)
            target.body_observations += 1

    def person_id_at(self, key: TrackKey, frame: int) -> int | None:
        st = self.tracks.get(key)
        if st is None:
            return None
        for seg in reversed(st.segments):
            if int(frame) >= seg.start_frame and (seg.end_frame is None or int(frame) <= seg.end_frame):
                return seg.person_id
        return st.person_id

    # ------------------------------ track state -------------------------------
    def ensure_track(self, key: TrackKey, frame: int) -> TrackBinding:
        st = self.tracks.get(key)
        if st is None:
            st = TrackBinding(key=key, first_frame=int(frame), last_frame=int(frame))
            self.tracks[key] = st
            self.events.append({
                "frame": int(frame), "camera": key[0], "track_id": key[1],
                "event": "track_created", "person_id": None,
            })
        return st

    def touch_track(self, key: TrackKey, frame: int, bbox: np.ndarray, *, ambiguous: bool = False) -> TrackBinding:
        st = self.ensure_track(key, frame)
        st.last_frame = max(st.last_frame, int(frame))
        b = np.asarray(bbox, dtype=np.float32).reshape(4).copy()
        if st.last_bbox is not None:
            st.prev_bbox = st.last_bbox.copy()
            st.prev_bbox_frame = int(frame) - 1
        st.last_bbox = b
        if ambiguous:
            st.ambiguous_frames += 1
            st.safe_after_frame = max(st.safe_after_frame, int(frame) + self.ambiguity_grace_frames)
        if st.person_id is not None and not ambiguous:
            self._update_profile_geometry(st, frame)
        else:
            # Crossing pauses LEARNING, not continuity. A short tracker blink is
            # exactly when the recent-person lease is most valuable.
            self._try_motion_only_lease(st, frame, ambiguous=ambiguous)
        return st

    def maybe_seed_person(self, key: TrackKey, frame: int) -> int | None:
        st = self.ensure_track(key, frame)
        if st.person_id is not None:
            return st.person_id
        if st.age < self.new_person_after_frames or int(frame) < st.safe_after_frame:
            return None

        # Conservative G Reacquisition
        decision = self.conservative_g_reacquisition(st, frame, body_feat=st.last_body)
        target = self.profiles.get(decision.candidate_person_id) if decision.candidate_person_id is not None else None
        event = {
            "camera": st.key[0], "frame": int(frame), "raw_track_id": None,
            "object_id": f"O{st.key[1]:03d}",
            "before_global_id": f"G{st.person_id:03d}" if st.person_id is not None else None,
            "candidate_global_id": f"G{decision.candidate_person_id:03d}" if decision.candidate_person_id is not None else None,
            **decision.as_dict(), "after_global_id": None,
            "face_authority": self.face_diagnostic(st.key).decision if self.face_diagnostic(st.key) else None,
            "face_score": self.face_diagnostic(st.key).top1_score if self.face_diagnostic(st.key) else None,
            "face_conflict": bool(st.strong_face_conflict),
        }
        if decision.state == "MATCH" and target is not None:
            self._bind(st, target, frame, "conservative_g_reacquire", reacquire=True)
            event["after_global_id"] = f"G{target.person_id:03d}"
            self.body_decision_events.append(event)
            self.decisions.append(PersonDecision(
                frame=int(frame), camera=st.key[0], track_id=st.key[1], person_id=target.person_id,
                reason="conservative_g_reacquire", accepted=True,
            ))
            return target.person_id

        if decision.state == "ABSTAIN" and (
            decision.reason == "NO_ELIGIBLE_CANDIDATE"
            or decision.reason == "INSUFFICIENT_BODY_SAMPLES"
        ):
            p = self._new_profile(st, frame, reason="NEW_G_STABLE_TRACK")
            event["after_global_id"] = f"G{p.person_id:03d}"
            self.body_decision_events.append(event)
            return p.person_id

        self.body_decision_events.append(event)
        return None

    def _bind(self, st: TrackBinding, profile: PersonProfile, frame: int, reason: str, *, reacquire: bool = False) -> None:
        # Motion/body may bind only an unbound local track. Only trusted FACE
        # authority is allowed to split/rebind an already-bound local track.
        if st.person_id is not None:
            return
        authority = "face" if reason in {
            "face_authority_rebind", "new_face_identity", "trusted_face_reacquire",
            "face_global_reacquire", "employee_face_seed",
        } else "continuity"
        self._set_binding(st, profile, frame, reason, authority=authority, reacquire=reacquire, allow_rebind=False)

    def _set_binding(
        self, st: TrackBinding, profile: PersonProfile, frame: int, reason: str, *,
        authority: str, reacquire: bool = False, allow_rebind: bool = False,
    ) -> bool:
        old_pid = st.person_id
        if old_pid is not None and old_pid != profile.person_id and not allow_rebind:
            return False
        if old_pid == profile.person_id:
            return True
        switch_frame = int(frame if frame is not None else st.last_frame)
        if st.segments and st.segments[-1].end_frame is None:
            if switch_frame <= st.segments[-1].start_frame:
                st.segments[-1].person_id = profile.person_id
                st.segments[-1].authority = authority
                st.segments[-1].reason = reason
            else:
                st.segments[-1].end_frame = max(switch_frame - 1, st.segments[-1].start_frame)
                st.segments.append(TrackSegment(switch_frame, None, profile.person_id, reason, authority))
        else:
            st.segments.append(TrackSegment(switch_frame, None, profile.person_id, reason, authority))
        st.person_id = profile.person_id
        st.bind_reason = reason
        if st.key not in profile.members:
            profile.members.append(st.key)
        if reacquire:
            profile.reacquire_count += 1
        if authority != "face":
            st.body_promotion_state = "BLOCKED_NO_FACE_AUTHORITY"
        self._update_profile_geometry(st, frame)
        event = "face_segment_rebind" if old_pid is not None and old_pid != profile.person_id else "bind"
        self.events.append({
            "frame": int(frame), "camera": st.key[0], "track_id": st.key[1],
            "event": event, "person_id": profile.person_id, "from_person_id": old_pid,
            "reason": reason, "authority": authority, "reacquire": bool(reacquire),
        })
        return True

    def _new_profile(self, st: TrackBinding, frame: int, reason: str) -> PersonProfile:
        p = PersonProfile(person_id=self._next_person_id)
        self._next_person_id += 1
        self.profiles[p.person_id] = p
        self._bind(st, p, frame, reason, reacquire=False)
        self.decisions.append(PersonDecision(
            frame=int(frame), camera=st.key[0], track_id=st.key[1], person_id=p.person_id,
            reason="new_person", accepted=True,
        ))
        return p

    def replace_track_identity(
        self, st: TrackBinding, profile: PersonProfile, reason: str, *,
        score: float | None = None, authority: str | None = None, frame: int | None = None,
    ) -> None:
        """Replace the final assignment for a completed tracklet without overlapping segments."""
        old_pid = st.person_id
        segment_authority = authority or ("face" if "face" in reason or "fusion" in reason else "continuity")
        st.segments = [TrackSegment(st.first_frame, None, profile.person_id, reason, segment_authority)]
        st.person_id = profile.person_id
        st.bind_reason = reason
        if st.key not in profile.members:
            profile.members.append(st.key)
        if old_pid != profile.person_id:
            profile.reacquire_count += 1
            if frame is not None:
                st.identity_change_until = max(st.identity_change_until, int(frame) + 30)
            st.identity_change_count += 1
        self.events.append({
            "frame": int(frame if frame is not None else st.last_frame), "camera": st.key[0], "track_id": st.key[1],
            "event": "track_identity_replaced", "from_person_id": old_pid,
            "person_id": profile.person_id, "reason": reason, "score": score,
        })

    def _update_profile_geometry(self, st: TrackBinding, frame: int) -> None:
        if st.person_id is None or st.last_bbox is None:
            return
        p = self.profiles[st.person_id]
        cam = st.key[0]
        if cam in p.last_bbox:
            p.prev_bbox[cam] = p.last_bbox[cam].copy()
            p.prev_bbox_frame[cam] = p.last_seen.get(cam, int(frame) - 1)
        p.last_bbox[cam] = st.last_bbox.copy()
        p.last_seen[cam] = int(frame)

    def _person_active_this_frame(self, pid: int, camera: str, frame: int, except_key: TrackKey | None = None) -> bool:
        for k, st in self.tracks.items():
            if except_key is not None and k == except_key:
                continue
            if k[0] == camera and st.person_id == pid and st.last_frame == int(frame):
                return True
        return False

    def _active_occlusion_hold(self, st: TrackBinding, frame: int) -> bool:
        """Hold an unbound O near an active P until an occlusion separates."""
        if st.last_bbox is None:
            return False
        for profile in self.profiles.values():
            if not self._person_active_this_frame(profile.person_id, st.key[0], frame, except_key=st.key):
                continue
            motion = self._motion_score(profile, st.key[0], frame, st.last_bbox)
            if motion is not None and motion >= 0.68:
                return True
        return False

    # -------------------------- short-gap continuity --------------------------
    @staticmethod
    def _center_size(box: np.ndarray) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = [float(v) for v in box]
        return 0.5 * (x1 + x2), 0.5 * (y1 + y2), max(x2 - x1, 1.0), max(y2 - y1, 1.0)

    @staticmethod
    def _iou(a: np.ndarray, b: np.ndarray) -> float:
        ax1, ay1, ax2, ay2 = [float(v) for v in a]
        bx1, by1, bx2, by2 = [float(v) for v in b]
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        inter = max(ix2 - ix1, 0.0) * max(iy2 - iy1, 0.0)
        aa = max(ax2 - ax1, 0.0) * max(ay2 - ay1, 0.0)
        bb = max(bx2 - bx1, 0.0) * max(by2 - by1, 0.0)
        return float(inter / max(aa + bb - inter, 1e-6))

    def _predict_bbox(self, p: PersonProfile, camera: str, frame: int) -> np.ndarray | None:
        last = p.last_bbox.get(camera)
        last_f = p.last_seen.get(camera)
        if last is None or last_f is None:
            return None
        prev = p.prev_bbox.get(camera)
        prev_f = p.prev_bbox_frame.get(camera)
        if prev is None or prev_f is None or last_f <= prev_f:
            return last.copy()
        dt = float(last_f - prev_f)
        gap = float(int(frame) - last_f)
        velocity = (last - prev) / max(dt, 1.0)
        pred = last + velocity * gap
        # Avoid exploding prediction across noisy bbox changes.
        lc = np.asarray(self._center_size(last))
        pc = np.asarray(self._center_size(pred))
        max_shift = max(lc[2], lc[3]) * max(1.5, gap * 0.6)
        shift = np.hypot(pc[0] - lc[0], pc[1] - lc[1])
        if shift > max_shift:
            scale = max_shift / max(shift, 1e-6)
            dx = (pc[0] - lc[0]) * scale
            dy = (pc[1] - lc[1]) * scale
            w, h = lc[2], lc[3]
            cx, cy = lc[0] + dx, lc[1] + dy
            pred = np.array([cx - w/2, cy - h/2, cx + w/2, cy + h/2], dtype=np.float32)
        return pred.astype(np.float32)

    def _motion_score(self, p: PersonProfile, camera: str, frame: int, new_box: np.ndarray) -> float | None:
        pred = self._predict_bbox(p, camera, frame)
        if pred is None:
            return None
        pcx, pcy, pw, ph = self._center_size(pred)
        ncx, ncy, nw, nh = self._center_size(new_box)
        diag = max(math.hypot(pw, ph), 1.0)
        dist = math.hypot(ncx - pcx, ncy - pcy) / diag
        center = math.exp(-2.8 * dist)
        iou = self._iou(pred, new_box)
        scale = math.exp(-abs(math.log(max((nw * nh) / max(pw * ph, 1.0), 1e-6))))
        return float(np.clip(0.55 * center + 0.30 * iou + 0.15 * scale, 0.0, 1.0))

    def _recent_candidates(self, st: TrackBinding, frame: int) -> list[tuple[PersonProfile, int, float]]:
        if st.last_bbox is None:
            return []
        cam = st.key[0]
        out: list[tuple[PersonProfile, int, float]] = []
        for p in self.profiles.values():
            last = p.last_seen.get(cam)
            if last is None:
                continue
            gap = int(frame) - int(last)
            if gap <= 0 or gap > self.short_gap_frames:
                continue
            if self._person_active_this_frame(p.person_id, cam, frame, except_key=st.key):
                continue
            ms = self._motion_score(p, cam, frame, st.last_bbox)
            if ms is not None:
                out.append((p, gap, ms))
        return out

    def _try_motion_only_lease(self, st: TrackBinding, frame: int, *, ambiguous: bool = False) -> bool:
        if st.person_id is not None or st.last_bbox is None:
            return False
        candidates = [(p, gap, ms) for p, gap, ms in self._recent_candidates(st, frame) if gap <= self.motion_only_gap_frames]
        candidates.sort(key=lambda x: x[2], reverse=True)
        if not candidates:
            return False
        best_p, _gap, best = candidates[0]
        second = candidates[1][2] if len(candidates) > 1 else 0.0
        margin = best - second
        # Pure motion is intentionally allowed only for very short gaps and a
        # clear winner. This solves detector/tracker blinks without global ReID.
        min_score = 0.86 if ambiguous else 0.80
        min_margin = 0.16 if ambiguous else 0.12
        if best >= min_score and margin >= min_margin:
            self._bind(st, best_p, frame, "short_gap_motion_lease", reacquire=True)
            self.decisions.append(PersonDecision(
                frame=int(frame), camera=st.key[0], track_id=st.key[1], person_id=best_p.person_id,
                reason="short_gap_motion_lease", accepted=True, score=best, margin=margin,
                motion_score=best,
            ))
            return True
        return False

    def _body_descriptor(self, st: TrackBinding) -> tuple[np.ndarray, float | None, int] | None:
        samples = st.pending_body_samples
        if len(samples) < 2:
            return None
        vectors = np.stack([normalize(x["embedding"]) for x in samples]).astype(np.float32)
        centroid = normalize(vectors.mean(axis=0)).astype(np.float32)
        pairwise = vectors @ vectors.T
        values = pairwise[np.triu_indices(len(vectors), 1)]
        self_consistency = float(np.median(values)) if len(values) else None
        return centroid, self_consistency, len(vectors)

    def conservative_g_reacquisition(
        self, st: TrackBinding, frame: int, body_feat: np.ndarray | None = None
    ) -> BodyAssociationDecision:
        """Evaluate O-to-profile continuity without treating one body frame as identity."""
        if st.strong_face_conflict or st.body_quarantined:
            result = BodyAssociationDecision("CANNOT_LINK", reason="FACE_CONFLICT")
            st.last_body_decision = result
            return result
        if st.last_bbox is None:
            result = BodyAssociationDecision("ABSTAIN", reason="NO_BBOX")
            st.last_body_decision = result
            return result

        descriptor = self._body_descriptor(st)
        if descriptor is None:
            result = BodyAssociationDecision(
                "ABSTAIN", sample_count=len(st.pending_body_samples), reason="INSUFFICIENT_BODY_SAMPLES",
            )
            st.last_body_decision = result
            return result
        centroid, consistency, sample_count = descriptor
        cam = st.key[0]
        candidates: list[tuple[PersonProfile, float, float, float, float]] = []
        blocked_active = False
        for p in self.profiles.values():
            last = p.last_seen.get(cam)
            if last is None:
                continue
            gap = int(frame) - int(last)
            active = self._person_active_this_frame(p.person_id, cam, frame, except_key=st.key)
            if active and gap <= 0 and p.body_bank:
                active_score = max(
                    max(float(sample["embedding"] @ item.embedding) for item in p.body_bank)
                    for sample in st.pending_body_samples
                )
                if active_score >= self.body_short_gap_near:
                    blocked_active = True
                continue
            if gap <= 0 or gap > self.short_gap_frames:
                continue
            motion = self._motion_score(p, cam, frame, st.last_bbox)
            if motion is None or motion < 0.20 or not p.body_bank:
                continue
            # Use one score per O sample, then robustly aggregate the best five.
            per_sample = []
            for sample in st.pending_body_samples:
                per_sample.append(max(float(sample["embedding"] @ item.embedding) for item in p.body_bank))
            per_sample.sort(reverse=True)
            robust = float(np.mean(per_sample[:min(5, len(per_sample))]))
            centroid_score = max(float(centroid @ item.embedding) for item in p.body_bank)
            body_gate = self.body_short_gap_near if gap <= 15 else self.body_short_gap_far
            if active:
                if robust >= body_gate:
                    blocked_active = True
                continue
            combined = 0.35 * motion + 0.65 * robust
            candidates.append((p, combined, centroid_score, robust, motion))

        if not candidates:
            reason = "SIMULTANEOUS_CANNOT_LINK" if blocked_active else "NO_ELIGIBLE_CANDIDATE"
            result = BodyAssociationDecision(
                "CANNOT_LINK" if blocked_active else "ABSTAIN",
                sample_count=sample_count, self_consistency=consistency, reason=reason,
            )
            st.last_body_decision = result
            return result

        candidates.sort(key=lambda x: x[1], reverse=True)
        best, second = candidates[0], candidates[1] if len(candidates) > 1 else None
        margin = best[1] - second[1] if second else None
        body_gate = self.body_short_gap_near if (frame - best[0].last_seen.get(cam, frame)) <= 15 else self.body_short_gap_far
        if second and margin is not None and margin < self.body_match_margin:
            state, reason = "ABSTAIN", "AMBIGUOUS_MARGIN"
        elif sample_count < 3 or (consistency is not None and consistency < self.body_short_gap_near):
            state, reason = "ABSTAIN", "LOW_SELF_CONSISTENCY"
        elif best[3] < body_gate or best[1] < 0.74:
            state, reason = "ABSTAIN", "INSUFFICIENT_ROBUST_EVIDENCE"
        else:
            state, reason = "MATCH", "ROBUST_BODY_MOTION_MATCH"
        result = BodyAssociationDecision(
            state, best[0].person_id if state == "MATCH" else None,
            body_score=best[3], body_centroid_score=best[2], body_robust_score=best[3],
            motion_score=best[4], combined_score=best[1],
            runner_up_person_id=second[0].person_id if second else None,
            runner_up_score=second[1] if second else None, margin=margin,
            sample_count=sample_count, self_consistency=consistency, reason=reason,
        )
        st.last_body_decision = result
        return result

    # ------------------------------ face authority ------------------------------
    def _face_bank_vectors(self, p: PersonProfile, camera: str, frame: int) -> list[np.ndarray]:
        vectors = [x.embedding for x in p.face_core()]
        if (
            p.recent_face_embedding is not None
            and p.recent_face_camera == camera
            and 0 <= int(frame) - int(p.recent_face_frame) <= self.face_recent_anchor_frames
        ):
            vectors.append(p.recent_face_embedding)
        return vectors

    def _rank_face(self, key: TrackKey, frame: int, embedding: np.ndarray) -> FaceRankResult:
        st = self.tracks.get(key)
        current_pid = st.person_id if st is not None else None
        banks: dict[int, list[np.ndarray]] = {}
        for pid, p in self.profiles.items():
            # A P already active on another local track in the same frame should
            # not normally be stolen. The current P is always allowed so AdaFace
            # can explicitly verify continuity.
            if pid != current_pid and self._person_active_this_frame(pid, key[0], frame, except_key=key):
                continue
            vectors = self._face_bank_vectors(p, key[0], frame)
            if vectors:
                banks[pid] = vectors
        return self.face_recognizer.rank(embedding, banks)

    def _rank_face_global(self, key: TrackKey, frame: int, embedding: np.ndarray) -> FaceRankResult:
        """Rank against all profiles, including profiles active on another track.

        This is used only after a new-face candidate has accumulated enough
        trusted evidence, preventing a tracker split from minting a duplicate
        identity while preserving the normal active-track theft guard.
        """
        # This path is entered only after a multi-frame new-face candidate has
        # accumulated. Unlike normal per-frame ranking, it must also consider
        # an active profile: a tracker split can leave the original O visible
        # while the replacement O is already carrying the same face.
        banks = {
            pid: [item.embedding for item in profile.face_core()]
            for pid, profile in self.profiles.items()
            if profile.face_core()
        }
        return self.face_recognizer.rank(embedding, banks)

    def _set_face_diag(
        self, key: TrackKey, frame: int, *, decision: str, accepted: bool,
        rank: FaceRankResult | None, votes: int, pose: str, tier: str, quality: float,
    ) -> FaceAuthorityResult:
        st = self.tracks.get(key)
        out = FaceAuthorityResult(
            frame=int(frame),
            person_id=st.person_id if st is not None else None,
            decision=decision,
            accepted=bool(accepted),
            top1_person_id=rank.top1_person_id if rank else None,
            top1_score=rank.top1_score if rank else None,
            top2_person_id=rank.top2_person_id if rank else None,
            top2_score=rank.top2_score if rank else None,
            margin=rank.margin if rank else None,
            candidate_votes=int(votes),
            candidate_needed=self.face_match_confirmations,
            pose=pose,
            tier=tier,
            quality=float(quality),
        )
        self._face_diagnostics[key] = out
        return out

    def _vote_face_pid(self, st: TrackBinding, pid: int, frame: int) -> int:
        if st.face_candidate_pid == pid and 0 <= int(frame) - st.face_candidate_last_frame <= self.face_candidate_max_gap:
            st.face_candidate_votes += 1
        else:
            st.face_candidate_pid = int(pid)
            st.face_candidate_votes = 1
        st.face_candidate_last_frame = int(frame)
        return st.face_candidate_votes

    def _reset_face_pid_vote(self, st: TrackBinding) -> None:
        st.face_candidate_pid = None
        st.face_candidate_votes = 0
        st.face_candidate_last_frame = -1

    def _vote_new_face(self, st: TrackBinding, embedding: np.ndarray, frame: int) -> int:
        e = normalize(embedding).astype(np.float32)
        keep = False
        if st.new_face_candidate is not None and 0 <= int(frame) - st.new_face_last_frame <= self.face_candidate_max_gap:
            sim = float(e @ st.new_face_candidate)
            # Pose and illumination changes between adjacent CCTV frames can
            # move the embedding more than a same-person identity match. Keep
            # candidate continuity permissive; final creation still requires
            # multiple trusted observations and face quality gating.
            keep = sim >= 0.62
        if keep:
            w = min(st.new_face_votes, 4)
            st.new_face_candidate = normalize((w * st.new_face_candidate + e) / (w + 1)).astype(np.float32)
            st.new_face_votes += 1
        else:
            st.new_face_candidate = e
            st.new_face_votes = 1
        st.new_face_last_frame = int(frame)
        return st.new_face_votes

    def _reset_new_face_vote(self, st: TrackBinding) -> None:
        st.new_face_candidate = None
        st.new_face_votes = 0
        st.new_face_last_frame = -1

    def _queue_current_face_view(
        self, st: TrackBinding, key: TrackKey, frame: int, embedding: np.ndarray,
        quality: float, pose: str, aligned_crop: np.ndarray | None,
    ) -> int:
        """Require two coherent observations before learning a new current-P view."""
        e = normalize(embedding).astype(np.float32)
        same_sequence = (
            st.current_face_view_candidate is not None
            and st.current_face_view_pose == pose
            and 0 <= int(frame) - st.current_face_view_last_frame <= self.face_candidate_max_gap
            and float(e @ st.current_face_view_candidate) >= 0.62
        )
        if not same_sequence:
            st.current_face_view_candidate = e
            st.current_face_view_pose = pose
            st.current_face_view_samples = []
        st.current_face_view_candidate = normalize(
            (st.current_face_view_candidate + e) * 0.5
        ).astype(np.float32)
        st.current_face_view_last_frame = int(frame)
        st.current_face_view_samples.append({
            "frame": int(frame), "embedding": e, "quality": float(quality),
            "pose": pose, "crop": aligned_crop,
        })
        if len(st.current_face_view_samples) < 2:
            return len(st.current_face_view_samples)
        profile = self.profiles.get(st.person_id)
        if profile is not None:
            for sample in sorted(st.current_face_view_samples, key=lambda x: x["quality"], reverse=True):
                self._learn_face_sample(
                    profile, key, sample["frame"], sample["embedding"],
                    sample["quality"], sample["pose"], "support", sample["crop"],
                )
        st.current_face_view_candidate = None
        st.current_face_view_pose = ""
        st.current_face_view_last_frame = -1
        st.current_face_view_samples = []
        return 2

    def _learn_face_sample(
        self, p: PersonProfile, key: TrackKey, frame: int, embedding: np.ndarray,
        quality: float, pose: str, tier: str, aligned_crop: np.ndarray | None,
    ) -> None:
        changed, slot = self._add_face(p, embedding, quality, pose, tier, frame)
        p.face_observations += 1
        if tier in TRUSTED_FACE_TIERS:
            p.face_anchor_count += 1
            p.recent_face_embedding = normalize(embedding).astype(np.float32)
            p.recent_face_quality = float(quality)
            p.recent_face_pose = pose
            p.recent_face_frame = int(frame)
            p.recent_face_camera = key[0]
        if changed and aligned_crop is not None:
            sample = self.store.save_face(p.person_id, pose, slot, aligned_crop)
            if sample:
                pose_items = [x for x in p.face_bank if x.pose == pose]
                if 0 <= slot < len(pose_items):
                    pose_items[slot].sample_file = sample
            self.store.write_metadata(p)

    def observe_face(
        self,
        key: TrackKey,
        frame: int,
        embedding: np.ndarray,
        quality: float,
        pose: str,
        tier: str,
        *,
        aligned_crop: np.ndarray | None = None,
        gallery_employee: str | None = None,
        gallery_accepted: bool = False,
    ) -> FaceAuthorityResult:
        """Run anonymous AdaFace recognition and apply FACE authority.

        Trusted face is the only cue allowed to correct P on an already-bound
        local track. The correction starts a new track segment at `frame`; it
        never rewrites earlier history. Body/motion cannot perform this rebind.
        """
        st = self.ensure_track(key, frame)
        st.face_observations += 1
        if aligned_crop is not None and tier != "reject":
            if self.store.save_face_evidence(key[0], key[1], frame, pose, aligned_crop) is not None:
                st.face_evidence_count += 1
        trusted = tier in TRUSTED_FACE_TIERS and quality >= self.face_learn_quality

        if not trusted:
            return self._set_face_diag(
                key, frame, decision="SKIP_WEAK_FACE", accepted=False, rank=None,
                votes=0, pose=pose, tier=tier, quality=quality,
            )

        rank = self._rank_face(key, frame, embedding)
        current_pid = st.person_id

        # A bound profile must keep learning new poses. If the new view is not
        # strong enough for a normal match, retain it as a two-frame candidate
        # instead of treating every pose change as an identity conflict.
        if (
            current_pid is not None
            and not st.learning_frozen
            and not st.strong_face_conflict
            and not st.body_quarantined
        ):
            current = self.profiles[current_pid]
            current_vectors = current.face_core()
            current_score = max(
                (float(normalize(embedding) @ item.embedding) for item in current_vectors),
                default=-1.0,
            )
            top_is_safe = (
                rank.top1_person_id is None
                or rank.top1_person_id == current_pid
                or rank.top1_score is None
                or current_score >= float(rank.top1_score) - 0.02
            )
            if current_score >= self.face_view_update_threshold and top_is_safe:
                view_votes = self._queue_current_face_view(
                    st, key, frame, embedding, quality, pose, aligned_crop,
                )
                return self._set_face_diag(
                    key, frame,
                    decision="FACE_VIEW_LEARNED_CURRENT" if view_votes >= 2 else "FACE_VIEW_CANDIDATE_CURRENT",
                    accepted=view_votes >= 2, rank=rank, votes=view_votes,
                    pose=pose, tier=tier, quality=quality,
                )

        # 1) AdaFace recognizes an existing anonymous P. Require temporal
        # confirmation before changing P, except when it simply verifies the
        # already-bound P.
        if rank.accepted and rank.top1_person_id is not None:
            target_pid = int(rank.top1_person_id)
            target = self.profiles[target_pid]
            if current_pid == target_pid:
                self._reset_face_pid_vote(st)
                self._reset_new_face_vote(st)
                if st.learning_frozen:
                    st.frozen_face_confirmations += 1
                    if st.frozen_face_confirmations < 2:
                        return self._set_face_diag(
                            key, frame, decision="FACE_REVERIFY_CANDIDATE", accepted=False, rank=rank,
                            votes=st.frozen_face_confirmations, pose=pose, tier=tier, quality=quality,
                        )
                    st.learning_frozen = False
                    st.frozen_since_frame = None
                    st.frozen_face_confirmations = 0
                    st.body_promotion_state = "PENDING"
                self._learn_face_sample(target, key, frame, embedding, quality, pose, tier, aligned_crop)
                st.current_face_confirmations += 1
                if st.strong_face_conflict and st.current_face_confirmations >= 2:
                    st.strong_face_conflict = False
                    st.appearance_jump_until = -1
                    st.safe_after_frame = -1
                    st.last_body = None
                    st.last_body_frame = None
                    target.conflict_count = max(0, target.conflict_count - 1)
                    self.events.append({
                        "frame": int(frame), "camera": key[0], "track_id": key[1],
                        "event": "face_conflict_recovered", "person_id": target.person_id,
                        "confirmations": st.current_face_confirmations,
                    })
                if gallery_accepted and gallery_employee:
                    self.confirm_employee(key, frame, gallery_employee, source="gallery_face")
                return self._set_face_diag(
                    key, frame, decision="FACE_VERIFIED_CURRENT", accepted=True, rank=rank,
                    votes=self.face_match_confirmations, pose=pose, tier=tier, quality=quality,
                )

            votes = self._vote_face_pid(st, target_pid, frame)
            self._reset_new_face_vote(st)
            if votes >= self.face_match_confirmations:
                old_pid = st.person_id
                self._set_binding(
                    st, target, frame, "face_authority_rebind", authority="face",
                    reacquire=True, allow_rebind=True,
                )
                if old_pid is not None and old_pid != target_pid:
                    st.strong_face_conflict = True
                    st.current_face_confirmations = 0
                    self.events.append({
                        "frame": int(frame), "camera": key[0], "track_id": key[1],
                        "event": "face_authority_corrected_segment",
                        "from_person_id": old_pid, "to_person_id": target_pid,
                        "face_score": rank.top1_score, "margin": rank.margin,
                    })
                self.decisions.append(PersonDecision(
                    frame=int(frame), camera=key[0], track_id=key[1], person_id=target_pid,
                    reason="face_authority_rebind" if old_pid is not None else "trusted_face_reacquire",
                    accepted=True, score=rank.top1_score, margin=rank.margin, face_score=rank.top1_score,
                ))
                self._reset_face_pid_vote(st)
                self._learn_face_sample(target, key, frame, embedding, quality, pose, tier, aligned_crop)
                if gallery_accepted and gallery_employee:
                    self.confirm_employee(key, frame, gallery_employee, source="gallery_face")
                if not st.strong_face_conflict and not st.body_quarantined:
                    self.promote_body_if_authorized(key, frame, "FACE_CONFIRMED")
                return self._set_face_diag(
                    key, frame, decision="FACE_REBOUND_EXISTING_P", accepted=True, rank=rank,
                    votes=self.face_match_confirmations, pose=pose, tier=tier, quality=quality,
                )

            return self._set_face_diag(
                key, frame, decision="FACE_MATCH_CANDIDATE", accepted=False, rank=rank,
                votes=votes, pose=pose, tier=tier, quality=quality,
            )

        # 2) No existing face profile passed open-set threshold/margin.
        self._reset_face_pid_vote(st)
        if st.person_id is not None:
            current = self.profiles[st.person_id]
            if not current.face_core():
                # A provisional continuity P is not promoted to a face identity
                # from one frame. Require the same multi-frame face confirmation
                # used when creating a brand-new anonymous face identity.
                votes = self._vote_new_face(st, embedding, frame)
                if votes < self.face_new_confirmations:
                    return self._set_face_diag(
                        key, frame, decision="FACE_ANCHOR_CANDIDATE", accepted=False, rank=rank,
                        votes=votes, pose=pose, tier=tier, quality=quality,
                    )
                self._learn_face_sample(current, key, frame, embedding, quality, pose, tier, aligned_crop)
                self._reset_new_face_vote(st)
                if st.segments and st.segments[-1].person_id == current.person_id:
                    st.segments[-1].authority = "face"
                    st.segments[-1].reason = "new_face_identity"
                    st.bind_reason = "new_face_identity"
                    self.promote_body_if_authorized(key, frame, "NEW_FACE_IDENTITY")
                if gallery_accepted and gallery_employee:
                    self.confirm_employee(key, frame, gallery_employee, source="gallery_face")
                return self._set_face_diag(
                    key, frame, decision="FACE_ANCHORED_CURRENT_P", accepted=True, rank=rank,
                    votes=self.face_new_confirmations, pose=pose, tier=tier, quality=quality,
                )

            # Existing face-anchored P + unmatched trusted face: do NOT pollute
            # that P. Treat it as a possible tracker switch, pause learning, and
            # keep identity unchanged until a known P is positively recognized.
            current.conflict_count += 1
            st.strong_face_conflict = True
            st.body_quarantined = True
            st.body_promotion_state = "QUARANTINED"
            st.body_quarantine_reason = "FACE_UNKNOWN_CONFLICT_HOLD_P"
            st.current_face_confirmations = 0
            st.safe_after_frame = max(st.safe_after_frame, int(frame) + self.ambiguity_grace_frames * 2)
            self.events.append({
                "frame": int(frame), "camera": key[0], "track_id": key[1],
                "event": "trusted_face_unknown_conflict", "person_id": current.person_id,
                "top1_person_id": rank.top1_person_id, "top1_score": rank.top1_score,
                "margin": rank.margin,
            })
            return self._set_face_diag(
                key, frame, decision="FACE_UNKNOWN_CONFLICT_HOLD_P", accepted=False, rank=rank,
                votes=0, pose=pose, tier=tier, quality=quality,
            )

        # 3) Unbound track with a trusted but unseen face. Build a short
        # multi-frame candidate before minting a new anonymous face identity.
        # Body similarity may hold one frame during a suspected tracker switch,
        # but it must not permanently deadlock consistent trusted face evidence.
        votes = self._vote_new_face(st, embedding, frame)
        if st.last_body is not None:
            body_scores = [self._best_body_score(st.last_body, profile) or 0.0 for profile in self.profiles.values()]
            body_conflict_confirmations = max(self.face_new_confirmations, 2)
            if body_scores and max(body_scores) >= self.body_short_gap_near and votes < body_conflict_confirmations:
                st.strong_face_conflict = True
                st.current_face_confirmations = 0
                st.safe_after_frame = max(st.safe_after_frame, int(frame) + self.ambiguity_grace_frames * 2)
                return self._set_face_diag(
                    key, frame, decision="FACE_UNKNOWN_BODY_CONFLICT", accepted=False, rank=rank,
                    votes=votes, pose=pose, tier=tier, quality=quality,
                )
            if body_scores and max(body_scores) >= self.body_short_gap_near:
                st.strong_face_conflict = False
        if votes < self.face_new_confirmations:
            return self._set_face_diag(
                key, frame, decision="NEW_FACE_CANDIDATE", accepted=False, rank=rank,
                votes=votes, pose=pose, tier=tier, quality=quality,
            )

        if st.new_face_candidate is not None:
            if self._active_occlusion_hold(st, frame):
                return self._set_face_diag(
                    key, frame, decision="FACE_OCCLUSION_HOLD", accepted=False, rank=rank,
                    votes=votes, pose=pose, tier=tier, quality=quality,
                )
            global_rank = self._rank_face_global(key, frame, st.new_face_candidate)
            global_margin = global_rank.margin if global_rank.margin is not None else 1.0
            if (
                global_rank.top1_person_id is not None
                and global_rank.top1_score is not None
                and global_rank.top1_score >= max(self.face_match_threshold - 0.04, 0.64)
                and global_margin >= max(self.face_match_margin, 0.05)
            ):
                target = self.profiles[global_rank.top1_person_id]
                self._bind(st, target, frame, "face_global_reacquire", reacquire=True)
                self._reset_new_face_vote(st)
                self._learn_face_sample(target, key, frame, embedding, quality, pose, tier, aligned_crop)
                if not st.strong_face_conflict and not st.body_quarantined:
                    self.promote_body_if_authorized(key, frame, "FACE_CONFIRMED")
                return self._set_face_diag(
                    key, frame, decision="FACE_GLOBAL_REACQUIRE", accepted=True, rank=global_rank,
                    votes=votes, pose=pose, tier=tier, quality=quality,
                )

        p = self._new_profile(st, frame, reason="new_face_identity")
        self._reset_new_face_vote(st)
        self._learn_face_sample(p, key, frame, embedding, quality, pose, tier, aligned_crop)
        self.decisions.append(PersonDecision(
            frame=int(frame), camera=key[0], track_id=key[1], person_id=p.person_id,
            reason="new_face_identity", accepted=True,
        ))
        if gallery_accepted and gallery_employee:
            self.confirm_employee(key, frame, gallery_employee, source="gallery_face")
        if not st.strong_face_conflict and not st.body_quarantined:
            self.promote_body_if_authorized(key, frame, "NEW_FACE_IDENTITY")
        return self._set_face_diag(
            key, frame, decision="NEW_FACE_IDENTITY", accepted=True, rank=rank,
            votes=self.face_new_confirmations, pose=pose, tier=tier, quality=quality,
        )

    def _add_face(self, p: PersonProfile, embedding: np.ndarray, quality: float, pose: str, tier: str, frame: int) -> tuple[bool, int]:
        e = normalize(embedding).astype(np.float32)
        group = [x for x in p.face_bank if x.pose == pose]
        if group:
            sims = [float(e @ x.embedding) for x in group]
            best_i = int(np.argmax(sims))
            # Keep genuinely different views in the pose bank. Near-identical
            # frames still update support, while blur/pose changes below this
            # value get their own prototype for later matching.
            if sims[best_i] >= 0.84:
                item = group[best_i]
                old_quality = float(item.quality)
                # Once a pose has repeated support, near-identical frames are
                # verification evidence only. Do not keep EMA-updating the
                # canonical face with the same view.
                if item.support >= 2 and sims[best_i] >= 0.88:
                    item.last_frame = int(frame)
                    return False, best_i
                w = min(item.support, 6)
                item.embedding = normalize((w * item.embedding + e) / (w + 1)).astype(np.float32)
                item.support += 1
                item.quality = max(item.quality, float(quality))
                item.last_frame = int(frame)
                item.core = item.core or (item.support >= 2 and item.tier in TRUSTED_FACE_TIERS)
                if tier in TRUSTED_FACE_TIERS:
                    item.tier = tier
                return float(quality) > old_quality + 0.05, best_i
        if len(group) < self.max_face_per_pose:
            item = FaceMemoryItem(e, float(quality), pose, tier, 1, tier == "strong", int(frame), int(frame))
            p.face_bank.append(item)
            return True, len(group)
        slot = min(range(len(group)), key=lambda i: group[i].quality)
        weakest = group[slot]
        if float(quality) > weakest.quality + 0.08:
            weakest.embedding = e
            weakest.quality = float(quality)
            weakest.tier = tier
            weakest.support = 1
            weakest.core = tier == "strong"
            weakest.first_frame = int(frame)
            weakest.last_frame = int(frame)
            return True, slot
        return False, 0

    # ------------------------------ body memory -------------------------------
    @staticmethod
    def _best_body_score(embedding: np.ndarray, p: PersonProfile) -> float | None:
        bank = p.body_bank
        if not bank:
            return None
        q = normalize(embedding)
        return max(float(q @ x.embedding) for x in bank)

    def observe_body(
        self,
        key: TrackKey,
        frame: int,
        embedding: np.ndarray,
        quality: float,
        *,
        crop: np.ndarray | None = None,
        ambiguous: bool = False,
    ) -> int | None:
        """Store body evidence on this O only; never bind or promote from body."""
        st = self.ensure_track(key, frame)
        st.body_observations += 1
        e = normalize(embedding).astype(np.float32)
        if st.learning_frozen or ambiguous or float(quality) < self.body_learn_quality:
            return st.person_id
        st.last_body = e.copy()
        st.last_body_frame = int(frame)
        st.pending_body_samples.append({
            "frame": int(frame),
            "embedding": e.copy(),
            "quality": float(quality),
            "crop": crop.copy() if crop is not None else None,
        })
        st.pending_body_samples.sort(key=lambda item: float(item["quality"]), reverse=True)
        del st.pending_body_samples[15:]
        return st.person_id

    def promote_body_if_authorized(self, key: TrackKey, frame: int, reason: str) -> int:
        """Promotes quarantined body evidence of an instance into persistent profile memory."""
        st = self.tracks.get(key)
        if st is None or st.person_id is None:
            return 0
        if reason not in {"FACE_CONFIRMED", "GALLERY_CONFIRMED", "NEW_FACE_IDENTITY"}:
            st.body_promotion_state = "BLOCKED_NO_FACE_AUTHORITY"
            return 0
        if st.strong_face_conflict or st.body_quarantined:
            st.body_promotion_state = "BLOCKED_QUARANTINE"
            return 0
        if st.learning_frozen:
            st.body_promotion_state = "FROZEN_TRACK_GAP"
            return 0
        if not st.segments or st.segments[-1].authority != "face":
            st.body_promotion_state = "BLOCKED_NO_FACE_AUTHORITY"
            return 0
        if not st.pending_body_samples:
            st.body_promotion_state = "PROMOTED"
            return 0

        p = self.profiles[st.person_id]
        # Keep only a small, diverse representative set from this O.
        selected: list[dict] = []
        for sample in sorted(st.pending_body_samples, key=lambda item: float(item["quality"]), reverse=True):
            if not selected or max(float(sample["embedding"] @ x["embedding"]) for x in selected) < self.body_novelty_threshold:
                selected.append(sample)
            if len(selected) >= min(8, self.max_body_views):
                break

        promoted_any = False
        for sample in selected:
            changed, slot = self._add_body(p, sample["embedding"], sample["quality"], sample["frame"])
            if changed:
                p.body_observations += 1
                st.body_promoted_count += 1
            crop = sample.get("crop")
            if changed and crop is not None:
                sample_file = self.store.save_body(p.person_id, slot, crop)
                if sample_file and 0 <= slot < len(p.body_bank):
                    p.body_bank[slot].sample_file = sample_file
                promoted_any = True

        if promoted_any:
            self.store.write_metadata(p)
        st.pending_body_samples.clear()
        st.body_promotion_state = "PROMOTED" if selected else "PENDING"
        return len(selected)

    def _add_body(self, p: PersonProfile, e: np.ndarray, quality: float, frame: int) -> tuple[bool, int]:
        if p.body_bank:
            sims = [float(e @ x.embedding) for x in p.body_bank]
            best_i = int(np.argmax(sims))
            if sims[best_i] >= self.body_novelty_threshold:
                item = p.body_bank[best_i]
                if item.support >= 2 and sims[best_i] >= 0.93:
                    item.last_frame = int(frame)
                    return False, best_i
                old_quality = float(item.quality)
                w = min(item.support, 8)
                item.embedding = normalize((w * item.embedding + e) / (w + 1)).astype(np.float32)
                item.support += 1
                item.quality = max(item.quality, float(quality))
                item.last_frame = int(frame)
                item.core = item.core or item.support >= 3
                return float(quality) > old_quality + 0.08, best_i
        if len(p.body_bank) < self.max_body_views:
            p.body_bank.append(BodyMemoryItem(e.copy(), float(quality), 1, False, int(frame), int(frame)))
            return True, len(p.body_bank) - 1
        # Replace only weak singleton view with clearly better sample.
        candidate_indices = [i for i, x in enumerate(p.body_bank) if x.support <= 1]
        if candidate_indices:
            i = min(candidate_indices, key=lambda j: p.body_bank[j].quality)
            if float(quality) > p.body_bank[i].quality + 0.10:
                p.body_bank[i] = BodyMemoryItem(e.copy(), float(quality), 1, False, int(frame), int(frame))
                return True, i
        return False, 0

    # Face corrections are segment-level only. We intentionally do not
    # merge/rewrite entire historical profiles here; earlier frames remain auditable.

    # --------------------------- employee authority ---------------------------
    def confirm_employee(self, key: TrackKey, frame: int, employee_id: str, *, source: str) -> None:
        st = self.ensure_track(key, frame)
        if st.person_id is None:
            p = self._new_profile(st, frame, reason="employee_face_seed")
        else:
            p = self.profiles[st.person_id]
        # One employee cannot be confirmed on two simultaneous local tracks
        # in the same camera. Keep the later claim provisional and auditable.
        for other in self.profiles.values():
            if other.person_id == p.person_id or other.employee_id != employee_id:
                continue
            if any(member_camera == key[0] and self.tracks.get((member_camera, member), None) is not None
                   and self.tracks[(member_camera, member)].last_frame == int(frame)
                   for member_camera, member in other.members):
                self.events.append({
                    "frame": int(frame), "camera": key[0], "track_id": key[1],
                    "event": "employee_confirmation_blocked_duplicate",
                    "person_id": p.person_id, "employee_id": employee_id,
                    "source": source,
                })
                return
        if p.employee_id is None:
            p.employee_id = employee_id
            self.events.append({
                "frame": int(frame), "camera": key[0], "track_id": key[1],
                "event": "employee_confirmed", "person_id": p.person_id,
                "employee_id": employee_id, "source": source,
            })
        elif p.employee_id != employee_id:
            p.conflict_count += 1
            st.strong_face_conflict = True
            st.body_quarantined = True
            st.body_promotion_state = "QUARANTINED"
            st.body_quarantine_reason = "FACE_EMPLOYEE_CONFLICT"
            self.events.append({
                "frame": int(frame), "camera": key[0], "track_id": key[1],
                "event": "employee_face_reassigned", "person_id": p.person_id,
                "existing_employee_id": p.employee_id, "new_employee_id": employee_id,
            })
            return
        if source in {"gallery_face", "gallery_multi_frame"}:
            self.promote_body_if_authorized(key, frame, "GALLERY_CONFIRMED")

    # ------------------------------- exporting --------------------------------
    def payload(self) -> dict:
        profiles = []
        all_profs = {**self.archived_profiles, **self.profiles}
        for p in sorted(all_profs.values(), key=lambda x: x.person_id):
            profiles.append({
                "person_id": f"P{p.person_id:03d}",
                "employee_id": p.employee_id,
                "maturity": p.maturity(),
                "confidence": p.confidence(),
                "reacquire_count": p.reacquire_count,
                "face_anchor_count": p.face_anchor_count,
                "face_observations": p.face_observations,
                "body_observations": p.body_observations,
                "conflict_count": p.conflict_count,
                "recent_face": {
                    "frame": p.recent_face_frame,
                    "camera": p.recent_face_camera,
                    "pose": p.recent_face_pose,
                    "quality": p.recent_face_quality,
                } if p.recent_face_embedding is not None else None,
                "members": [{"camera": c, "track_id": int(t)} for c, t in p.members],
                "face_memory": [
                    {
                        "pose": x.pose, "tier": x.tier, "quality": x.quality,
                        "support": x.support, "core": x.core,
                        "first_frame": x.first_frame, "last_frame": x.last_frame,
                        "sample_file": x.sample_file,
                    }
                    for x in p.face_bank
                ],
                "body_memory": [
                    {
                        "quality": x.quality, "support": x.support, "core": x.core,
                        "first_frame": x.first_frame, "last_frame": x.last_frame,
                        "sample_file": x.sample_file,
                    }
                    for x in p.body_bank
                ],
            })
        tracks = []
        for st in sorted(self.tracks.values(), key=lambda x: (x.key[0], x.first_frame, x.key[1])):
            tracks.append({
                "camera": st.key[0], "track_id": st.key[1],
                "person_id": f"P{st.person_id:03d}" if st.person_id is not None else None,
                "bind_reason": st.bind_reason,
                "first_frame": st.first_frame, "last_frame": st.last_frame,
                "age": st.age,
                "face_observations": st.face_observations,
                "body_observations": st.body_observations,
                "ambiguous_frames": st.ambiguous_frames,
                "strong_face_conflict": st.strong_face_conflict,
                "body_promotion_state": st.body_promotion_state,
                "body_promoted_count": st.body_promoted_count,
                "body_quarantined": st.body_quarantined,
                "body_quarantine_reason": st.body_quarantine_reason,
                "learning_frozen": st.learning_frozen,
                "frozen_since_frame": st.frozen_since_frame,
                "frozen_face_confirmations": st.frozen_face_confirmations,
                "pending_body_count": len(st.pending_body_samples),
                "face_evidence_count": st.face_evidence_count,
                "segments": [
                    {
                        "start_frame": seg.start_frame, "end_frame": seg.end_frame,
                        "person_id": f"P{seg.person_id:03d}" if seg.person_id is not None else None,
                        "reason": seg.reason, "authority": seg.authority,
                    }
                    for seg in st.segments
                ],
            })
        decisions = [d.__dict__ for d in self.decisions]
        return {
            "mode": "face_anchor_authority_v3",
            "profiles": profiles,
            "tracks": tracks,
            "decisions": decisions,
            "events": self.events,
        }

    def save_metadata_all(self) -> None:
        for p in self.profiles.values():
            self.store.write_metadata(p)
