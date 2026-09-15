from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from src.embedding_store import EmbeddingRecord, EmbeddingStore
from src.identity_manager import IdentityManager
from src.identity_database import IdentityDatabase
from src.person_memory import PersonMemory, PersonProfile
from src.evidence_fusion import IdentityEvidence, TrackletEvidenceFusion
from src.gallery import GalleryHit
from src.face_detector import FaceDetection
from src.infer_engine import assign_faces_one_to_one


def test_embedding_store_round_trip_and_query():
    with tempfile.TemporaryDirectory() as root:
        store = EmbeddingStore(Path(root))
        store.add(EmbeddingRecord("f1", "face", "cam3", 10, 4, np.array([2.0, 0.0]), .9, 1, "front"))
        store.save()
        loaded = EmbeddingStore.load(root)
        result = loaded.query(np.array([1.0, 0.0]), kind="face")
        assert result[0][0].record_id == "f1"
        assert result[0][1] > .99


def test_full_frame_face_assignment_is_one_to_one_and_reports_ambiguity():
    boxes = [np.array([50, 10, 120, 180], dtype=np.float32), np.array([90, 15, 160, 185], dtype=np.float32)]
    keys = [("cam1", 41), ("cam1", 42)]
    one_face = FaceDetection(np.array([75, 20, 95, 50], dtype=np.float32), .92, np.zeros((5, 2)))
    assigned = assign_faces_one_to_one(boxes, keys, [one_face])
    assert sum(item["status"] == "ASSIGNED" for item in assigned.values()) == 1

    two_faces = [
        FaceDetection(np.array([65, 20, 85, 50], dtype=np.float32), .92, np.zeros((5, 2))),
        FaceDetection(np.array([125, 20, 145, 50], dtype=np.float32), .92, np.zeros((5, 2))),
    ]
    assigned = assign_faces_one_to_one(boxes, keys, two_faces)
    assert {item["face_index"] for item in assigned.values() if item["status"] == "ASSIGNED"} == {0, 1}


def test_full_frame_face_assignment_rejects_invalid_geometry():
    boxes = [np.array([50, 100, 120, 280], dtype=np.float32)]
    key = ("cam1", 41)
    invalid = FaceDetection(np.array([65, 260, 85, 290], dtype=np.float32), .99, np.zeros((5, 2)))
    result = assign_faces_one_to_one(boxes, [key], [invalid])
    assert result[key]["status"] == "NO_FACE"
    assert result[key]["face"] is None


def test_full_frame_face_assignment_marks_crossing_face_ambiguous():
    boxes = [np.array([50, 10, 120, 180], dtype=np.float32), np.array([90, 10, 160, 180], dtype=np.float32)]
    keys = [("cam1", 41), ("cam1", 42)]
    face = FaceDetection(np.array([95, 20, 115, 50], dtype=np.float32), .92, np.zeros((5, 2)))
    result = assign_faces_one_to_one(boxes, keys, [face])
    assert any(item["status"] == "AMBIGUOUS" for item in result.values())
    assert all(item["face"] is None for item in result.values())


def test_confirmed_identity_can_be_reassigned_by_repeated_evidence():
    manager = IdentityManager(min_confirmations=2, min_confirmation_weight=.5)
    a = GalleryHit("EMP001", .8, .1, .7, True, .55, .07)
    b = GalleryHit("EMP002", .8, .1, .7, True, .55, .07)
    manager.update(1, 1, a, .8, "strong")
    manager.update(1, 2, a, .8, "strong")
    manager.update(1, 3, b, .8, "strong")
    manager.update(1, 4, b, .8, "strong")
    assert manager.final(1).employee_id == "EMP002"


def test_identity_database_round_trip_query_and_assignment():
    with tempfile.TemporaryDirectory() as root:
        with IdentityDatabase(Path(root) / "identity.sqlite") as db:
            tracklet = db.upsert_tracklet("cam3", 7, 10)
            db.add_detection(tracklet, 10, np.array([1, 2, 30, 80]), .9, False)
            db.add_observation(
                tracklet, 10, "face", np.array([2.0, 0.0]), .8,
                pose="front", model_name="face", model_version="v1",
            )
            db.add_observation(
                tracklet, 11, "face", np.array([2.0, 0.0]), .8,
                pose="front", model_name="face", model_version="v1",
            )
            db.ensure_identity(3)
            db.assign(tracklet, 3, 10, "CONFIRMED", "test")
            db.promote_tracklet_references(tracklet, 3)
            db.ensure_identity(4)
            db.assign(tracklet, 4, 10, "CONFIRMED", "same_frame_correction")
            hits = db.search_identities([np.array([1.0, 0.0])], "face", "face", "v1")
            assert hits[0].identity_id == 4
            assert hits[0].score > .99
            assert hits[0].support == 1
            invalid = db.connection.execute(
                "SELECT COUNT(*) FROM assignments WHERE valid_to < valid_from"
            ).fetchone()[0]
            assert invalid == 0
            decision = TrackletEvidenceFusion().decide([
                IdentityEvidence(4, face_scores=[.8, .81], face_support=2)
            ])
            db.add_fusion_decision(tracklet, 10, decision)
            assert db.connection.execute("select count(*) from fusion_decisions").fetchone()[0] == 1
            assert db.integrity_check() == "ok"


def test_identity_database_separates_reused_track_ids_between_sessions():
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / "identity.sqlite"
        with IdentityDatabase(path, session_id="run-a") as db:
            first = db.upsert_tracklet("cam3", 1, 0)
        with IdentityDatabase(path, session_id="run-b") as db:
            second = db.upsert_tracklet("cam3", 1, 0)
        assert first != second


def test_canonical_database_export_isolated_from_source():
    with tempfile.TemporaryDirectory() as root:
        source = Path(root) / "source.sqlite"
        destination = Path(root) / "canonical.sqlite"
        with IdentityDatabase(source, session_id="source") as db:
            tracklet = db.upsert_tracklet("cam3", 1, 1)
            db.add_observation(tracklet, 1, "face", np.array([1.0, 0.0]), .8, model_name="face", model_version="v1")
            db.ensure_identity(1)
            db.assign(tracklet, 1, 1, "VERIFIED", "test")
            db.promote_tracklet_references(tracklet, 1)
            stats = db.export_canonical(destination)
            assert stats["observations"] == 1
        assert source.is_file() and destination.is_file()
        with IdentityDatabase(destination) as db:
            assert db.canonical_stats()["observations"] == 1
            assert db.integrity_check() == "ok"


def test_canonical_promotion_can_exclude_body_from_non_face_segment():
    with tempfile.TemporaryDirectory() as root:
        with IdentityDatabase(Path(root) / "identity.sqlite", session_id="run") as db:
            tracklet = db.upsert_tracklet("cam0", 1, 1)
            db.ensure_identity(1)
            db.add_observation(tracklet, 1, "face", np.array([1.0, 0.0]), .8, model_name="face", model_version="v1")
            db.add_observation(tracklet, 1, "body", np.array([1.0, 0.0]), .8, model_name="body", model_version="v1")
            db.assign(tracklet, 1, 1, "PROVISIONAL", "short_gap_motion_lease")
            db.promote_tracklet_references(tracklet, 1, include_body=False)
            assert db.connection.execute("select count(*) from observations where canonical=1 and kind='face'").fetchone()[0] == 1
            assert db.connection.execute("select count(*) from observations where canonical=1 and kind='body'").fetchone()[0] == 0


def test_assignment_intervals_keep_historical_observations_with_original_identity():
    with tempfile.TemporaryDirectory() as root:
        with IdentityDatabase(Path(root) / "identity.sqlite", session_id="run") as db:
            tracklet = db.upsert_tracklet("cam0", 1, 10)
            db.ensure_identity(1)
            db.ensure_identity(2)
            db.add_observation(tracklet, 10, "face", np.array([1.0, 0.0]), .9, model_name="face", model_version="v1")
            db.add_observation(tracklet, 20, "face", np.array([0.0, 1.0]), .9, model_name="face", model_version="v1")
            db.assign(tracklet, 1, 10, "CONFIRMED", "first_face")
            db.assign(tracklet, 2, 20, "CONFIRMED", "rebind_face")
            db.promote_tracklet_references(tracklet, 1, start_frame=10, end_frame=19)
            db.promote_tracklet_references(tracklet, 2, start_frame=20, end_frame=20)
            records = {record.frame: record.person_id for record in db.assigned_embedding_records()}
            assert records == {10: 1, 20: 2}


def test_canonical_export_is_idempotent_for_the_same_source_session():
    with tempfile.TemporaryDirectory() as root:
        source_path = Path(root) / "source.sqlite"
        destination = Path(root) / "canonical.sqlite"
        with IdentityDatabase(source_path, session_id="run") as source:
            tracklet = source.upsert_tracklet("cam0", 1, 1)
            source.ensure_identity(1)
            source.add_observation(tracklet, 1, "face", np.array([1.0, 0.0]), .9, model_name="face", model_version="v1")
            source.assign(tracklet, 1, 1, "CONFIRMED", "face")
            source.promote_tracklet_references(tracklet, 1, start_frame=1, end_frame=1)
            source.export_canonical(destination)
            with IdentityDatabase(destination, readonly=True) as target:
                first = target.canonical_stats()
            source.export_canonical(destination)
        with IdentityDatabase(destination, readonly=True) as target:
            assert target.canonical_stats() == first


def test_canonical_export_can_exclude_session_local_identities():
    with tempfile.TemporaryDirectory() as root:
        source = Path(root) / "source.sqlite"
        destination = Path(root) / "canonical.sqlite"
        with IdentityDatabase(source, session_id="source") as db:
            tracklet_a = db.upsert_tracklet("cam3", 1, 1)
            db.add_observation(tracklet_a, 1, "face", np.array([1.0, 0.0]), .8, model_name="face", model_version="v1")
            db.ensure_identity(1)
            db.assign(tracklet_a, 1, 1, "VERIFIED", "test")
            db.promote_tracklet_references(tracklet_a, 1)
            tracklet_b = db.upsert_tracklet("cam3", 2, 1)
            db.add_observation(tracklet_b, 1, "face", np.array([0.0, 1.0]), .8, model_name="face", model_version="v1")
            db.ensure_identity(2)
            db.assign(tracklet_b, 2, 1, "VERIFIED", "test")
            db.promote_tracklet_references(tracklet_b, 2)
            stats = db.export_canonical(destination, identity_ids={1})
            assert stats["identities"] == 1
        with IdentityDatabase(destination) as db:
            assert db.canonical_stats()["identities"] == 1
            assert db.connection.execute("SELECT COUNT(*) FROM identities WHERE id=2").fetchone()[0] == 0


def test_canonical_exports_keep_source_track_sessions_separate():
    with tempfile.TemporaryDirectory() as root:
        destination = Path(root) / "canonical.sqlite"
        for session, vector in (("source-a", [1.0, 0.0]), ("source-b", [0.0, 1.0])):
            source = Path(root) / f"{session}.sqlite"
            with IdentityDatabase(source, session_id=session) as db:
                tracklet = db.upsert_tracklet("cam3", 1, 1)
                db.add_observation(tracklet, 1, "face", np.array(vector), .8, model_name="face", model_version="v1")
                db.ensure_identity(1)
                db.assign(tracklet, 1, 1, "VERIFIED", "test")
                db.promote_tracklet_references(tracklet, 1)
                db.export_canonical(destination, identity_ids={1})
        with IdentityDatabase(destination) as db:
            assert db.connection.execute("SELECT COUNT(*) FROM tracklets").fetchone()[0] == 2


def test_confirmed_assignment_is_not_downgraded_by_provisional_pass():
    with tempfile.TemporaryDirectory() as root:
        with IdentityDatabase(Path(root) / "identity.sqlite", session_id="run") as db:
            tracklet = db.upsert_tracklet("cam3", 1, 1)
            db.ensure_identity(1)
            db.assign(tracklet, 1, 1, "CONFIRMED", "trusted_face")
            db.assign(tracklet, 1, 2, "PROVISIONAL", "online_bookkeeping")
            state = db.connection.execute(
                "SELECT state,valid_from,valid_to FROM assignments WHERE tracklet_id=? AND valid_to IS NULL",
                (tracklet,),
            ).fetchone()
            assert tuple(state) == ("CONFIRMED", 1, None)


def test_employee_confirmation_is_unique_for_simultaneous_tracks():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=False)
        first = ("cam0", 1)
        second = ("cam0", 2)
        for key, x in ((first, 0), (second, 300)):
            box = np.array([x, 0, x + 80, 160], dtype=np.float32)
            memory.touch_track(key, frame=5, bbox=box, ambiguous=False)
            memory.maybe_seed_person(key, frame=5)
        memory.confirm_employee(first, 5, "EMP001", source="test")
        memory.confirm_employee(second, 5, "EMP001", source="test")
        assert sum(p.employee_id == "EMP001" for p in memory.profiles.values()) == 1


def test_canonical_database_is_read_only():
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / "canonical.sqlite"
        with IdentityDatabase(path) as db:
            db.ensure_identity(1)
        with IdentityDatabase(path, readonly=True) as db:
            try:
                db.ensure_identity(2)
            except Exception:
                pass
            else:
                raise AssertionError("read-only canonical DB accepted a write")


def test_reconciliation_replaces_overlapping_segment_history():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=root, new_person_after_frames=1, require_face_before_person=False)
        key = ("cam3", 9)
        memory.touch_track(key, 10, np.array([0, 0, 20, 80], dtype=np.float32))
        old = memory.maybe_seed_person(key, 10)
        target_key = ("cam3", 3)
        memory.touch_track(target_key, 0, np.array([50, 0, 70, 80], dtype=np.float32))
        target = memory.maybe_seed_person(target_key, 0)
        state = memory.state_for_track(key)
        memory.replace_track_identity(state, memory.profiles[target], "test")
        assert old != target
        assert len(state.segments) == 1
        assert state.segments[0].start_frame == state.first_frame
        assert state.segments[0].person_id == target


def test_body_evidence_does_not_bind_or_promote_by_itself():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=root, new_person_after_frames=100, require_face_before_person=False)
        old = ("cam3", 1)
        new = ("cam3", 2)
        box = np.array([100, 100, 150, 250], dtype=np.float32)
        memory.touch_track(old, 0, box)
        old_pid = memory.maybe_seed_person(old, 0)  # no seed because age gate
        memory.touch_track(old, 100, box)
        old_pid = memory.maybe_seed_person(old, 100)
        memory.observe_body(old, 100, np.array([1.0, 0.0, 0.0]), 1.0)
        memory.touch_track(new, 107, box, ambiguous=True)
        assert memory.observe_body(new, 107, np.array([1.0, 0.0, 0.0]), 1.0) is None
        assert memory.observe_body(new, 108, np.array([1.0, 0.0, 0.0]), 1.0) is None
        memory.observe_body(new, 109, np.array([1.0, 0.0, 0.0]), 1.0)
        assert memory.state_for_track(new).person_id is None
        assert len(memory.state_for_track(new).pending_body_samples) == 3


def test_evidence_fusion_requires_independent_support_and_exposes_reason():
    fusion = TrackletEvidenceFusion()
    decision = fusion.decide([
        IdentityEvidence(2, face_scores=[.49, .48, .47], body_scores=[.90], face_support=3, body_support=3),
        IdentityEvidence(3, face_scores=[.85, .84], body_scores=[.60], face_support=2, body_support=1),
    ])
    assert decision.identity_id == 3
    assert decision.state == "CONFIRMED"
    assert decision.reason == "FACE_ONLY"


def test_evidence_fusion_rejects_ambiguous_candidates():
    fusion = TrackletEvidenceFusion()
    decision = fusion.decide([
        IdentityEvidence(2, face_scores=[.70, .69], face_support=2),
        IdentityEvidence(3, face_scores=[.69, .68], face_support=2),
    ])
    assert decision.state == "CONFLICT"
    assert decision.reason == "LOW_MARGIN"


def test_repeated_face_and_body_views_do_not_drift_prototypes():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=root, require_face_before_person=False)
        profile = PersonProfile(1)
        memory._add_face(profile, np.array([1.0, 0.0]), .8, "front", "support", 1)
        memory._add_face(profile, np.array([1.0, 0.0]), .8, "front", "support", 2)
        before_face = profile.face_bank[0].embedding.copy()
        memory._add_face(profile, np.array([.999, .01]), .9, "front", "support", 3)
        assert profile.face_bank[0].support == 2
        assert float(profile.face_bank[0].embedding @ before_face) > .999
        memory._add_body(profile, np.array([1.0, 0.0]), .8, 1)
        memory._add_body(profile, np.array([1.0, 0.0]), .8, 2)
        before_body = profile.body_bank[0].embedding.copy()
        memory._add_body(profile, np.array([.999, .01]), .9, 3)
        assert profile.body_bank[0].support == 2
        assert float(profile.body_bank[0].embedding @ before_body) > .999


def test_late_bound_track_backfills_only_matching_face_and_body_evidence():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=root, require_face_before_person=True)
        key = ("cam3", 95)
        st = memory.ensure_track(key, 0)
        target = memory._new_profile(st, 10, "test")
        memory._add_face(target, np.array([1.0, 0.0]), .8, "front", "support", 10)
        other = PersonProfile(2)
        memory.profiles[2] = other
        memory._add_face(other, np.array([0.0, 1.0]), .8, "front", "support", 10)
        memory._add_body(target, np.array([1.0, 0.0, 0.0]), .8, 10)
        memory._add_body(other, np.array([0.0, 1.0, 0.0]), .8, 10)

        observations = [
            SimpleNamespace(embedding=np.array([1.0, 0.0]), quality=.8, pose="front", tier="support", frame=1),
            SimpleNamespace(embedding=np.array([0.0, 1.0]), quality=.8, pose="front", tier="support", frame=2),
        ]
        memory.backfill_track_observations(key, observations, [
            np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]),
        ])
        assert target.face_observations == 1
        assert target.body_observations == 0
        assert len(target.face_bank) == 1
        assert len(target.body_bank) == 1


def test_body_conflict_blocks_new_face_identity_on_tracker_switch():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=root, face_new_confirmations=1, require_face_before_person=True)
        existing = PersonProfile(1)
        memory.profiles[1] = existing
        memory._next_person_id = 2
        memory._add_face(existing, np.array([1.0, 0.0, 0.0]), .8, "front", "support", 1)
        memory._add_body(existing, np.array([1.0, 0.0, 0.0]), .8, 1)
        key = ("cam3", 2)
        track = memory.ensure_track(key, 10)
        track.last_body = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        track.last_body_frame = 10
        result = memory.observe_face(key, 10, np.array([0.0, 0.0, 1.0]), .8, "front", "support")
        assert result.decision == "FACE_UNKNOWN_BODY_CONFLICT"
        assert len(memory.profiles) == 1
        result = memory.observe_face(key, 11, np.array([0.0, 0.0, 1.0]), .8, "front", "support")
        assert result.decision == "NEW_FACE_IDENTITY"
        assert len(memory.profiles) == 2


def test_prebind_body_backfill_and_conflict_recovery():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=root, face_match_threshold=.68, face_new_confirmations=2, require_face_before_person=True)
        key = ("cam0", 1)
        box = np.array([10, 10, 80, 180], dtype=np.float32)
        for frame in range(4):
            memory.touch_track(key, frame, box)
            memory.observe_body(key, frame, np.array([1.0, 0.0, 0.0]), .9)
        st = memory.state_for_track(key)
        assert st.person_id is None
        assert len(st.pending_body_samples) == 4

        memory.observe_face(key, 4, np.array([0.0, 1.0, 0.0]), .9, "front", "strong")
        result = memory.observe_face(key, 5, np.array([0.0, 1.0, 0.0]), .9, "front", "strong")
        assert result.decision == "NEW_FACE_IDENTITY"
        profile = memory.profile_for_track(key)
        assert profile is not None and profile.body_observations >= 1
        assert profile.body_bank and not st.pending_body_samples

        conflict = memory.observe_face(key, 6, np.array([0.0, 0.0, 1.0]), .9, "front", "strong")
        assert conflict.decision == "FACE_UNKNOWN_CONFLICT_HOLD_P"
        assert st.strong_face_conflict
        before = profile.body_observations
        memory.observe_body(key, 7, np.array([0.0, 0.0, 1.0]), .9)
        assert profile.body_observations == before

        memory.observe_face(key, 8, np.array([0.0, 1.0, 0.0]), .9, "front", "strong")
        memory.observe_face(key, 9, np.array([0.0, 1.0, 0.0]), .9, "front", "strong")
        assert not st.strong_face_conflict
        memory.observe_body(key, 10, np.array([0.9, 0.1, 0.0]), .9)


def test_same_track_body_stays_pending_without_face_authority():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=root, new_person_after_frames=1, require_face_before_person=False)
        key = ("cam0", 1)
        box = np.array([10, 10, 80, 180], dtype=np.float32)
        memory.touch_track(key, 0, box)
        memory.maybe_seed_person(key, 0)
        memory.observe_body(key, 1, np.array([1.0, 0.0, 0.0]), .9)
        before = len(memory.profiles[memory.state_for_track(key).person_id].body_bank)
        memory.observe_body(key, 2, np.array([0.8, 0.6, 0.0]), .9)
        profile = memory.profiles[memory.state_for_track(key).person_id]
        assert len(profile.body_bank) == before
        assert len(memory.state_for_track(key).pending_body_samples) == 2


def test_new_face_candidate_survives_small_pose_embedding_change():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=root, face_new_confirmations=3, require_face_before_person=True)
        key = ("cam0", 3)
        vectors = [
            np.array([1.0, 0.0, 0.0]),
            np.array([0.78, 0.625, 0.0]),
            np.array([0.80, 0.60, 0.0]),
        ]
        results = [memory.observe_face(key, frame, vector, .8, "front", "support")
                   for frame, vector in enumerate(vectors)]
        assert results[-1].decision == "NEW_FACE_IDENTITY"
        assert memory.state_for_track(key).person_id == 1


def test_split_track_reacquires_existing_face_profile_instead_of_minting_duplicate():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=root, face_match_threshold=.68, face_new_confirmations=2, require_face_before_person=True)
        original = memory.ensure_track(("cam0", 1), 0)
        profile = memory._new_profile(original, 0, "seed")
        memory._learn_face_sample(profile, original.key, 0, np.array([1.0, 0.0, 0.0]), .9, "front", "strong", None)
        split_key = ("cam0", 2)
        values = [np.array([.66, .751, 0.0]), np.array([.67, .742, 0.0])]
        results = [memory.observe_face(split_key, frame, value, .9, "front", "strong")
                   for frame, value in enumerate(values, start=10)]
        assert results[-1].decision == "FACE_GLOBAL_REACQUIRE"
        assert memory.state_for_track(split_key).person_id == profile.person_id
        assert len(memory.profiles) == 1
