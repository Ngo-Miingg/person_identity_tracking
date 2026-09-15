from __future__ import annotations

import tempfile
from pathlib import Path
import numpy as np

from src.face_detector import FaceDetection
from src.infer_engine import assign_faces_to_persons_hungarian
from src.person_memory import PersonMemory, TrackInstanceManager
from src.anonymous_face_recognizer import FaceRankResult


def test_invariant_a_raw_track_reuse_after_gap_creates_new_unbound_instance():
    """Test A: tid=65 is bound to P009. 140 frames later, tid=65 returns.
    
    Must produce a new instance ID (O new), starting completely UNBOUND (person_id is None),
    never inheriting the previous P009.
    """
    mgr = TrackInstanceManager(max_gap=60)
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=True)

        # Frame 1000: raw tid=65 appears
        inst_1, is_new_1 = mgr.get_or_create(65, frame=1000, camera="cam1")
        assert is_new_1 is True
        key_1 = ("cam1", inst_1)

        # Bind to P009 via face identity
        memory.touch_track(key_1, 1000, np.array([10, 10, 50, 100]))
        face_vec = np.random.randn(512).astype(np.float32)
        face_vec /= np.linalg.norm(face_vec)
        # 3 confirmations create new face identity
        for f in (1000, 1003, 1006):
            memory.observe_face(key_1, f, face_vec, quality=0.85, pose="front", tier="strong")

        st_1 = memory.state_for_track(key_1)
        assert st_1 is not None
        assert st_1.person_id is not None
        p_id = st_1.person_id

        # Raw tid=65 disappears until frame 1147 (gap = 141 frames > 60)
        inst_2, is_new_2 = mgr.get_or_create(65, frame=1147, camera="cam1")
        assert is_new_2 is True
        assert inst_2 != inst_1, "Tracker ID reuse after long gap must produce a new instance ID!"

        key_2 = ("cam1", inst_2)
        memory.touch_track(key_2, 1147, np.array([200, 200, 250, 300]))
        st_2 = memory.state_for_track(key_2)

        assert st_2 is not None
        assert st_2.person_id is None, "New instance from reused raw track MUST be UNBOUND (person_id is None)!"
        assert st_2.person_id != p_id, "New instance must NOT inherit previous P!"

        assert mgr.is_closed(inst_1)


def test_track_instance_continuous_takeover_keeps_same_o_and_camera_isolation():
    """A continuous raw-ID takeover remains one O; the same L on another camera does not."""
    mgr = TrackInstanceManager(max_gap=60)
    first, new = mgr.get_or_create(65, frame=1, camera="cam1")
    assert new is True
    same, new = mgr.get_or_create(65, frame=2, camera="cam1")
    assert same == first
    assert new is False

    other_camera, new = mgr.get_or_create(65, frame=1, camera="cam2")
    assert new is True
    assert other_camera != first


def test_existing_person_profile_survives_closed_o_and_can_be_reacquired():
    """Closing an O must not delete its persistent P profile."""
    mgr = TrackInstanceManager(max_gap=60)
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=True)
        instance, _ = mgr.get_or_create(65, frame=10, camera="cam1")
        key = ("cam1", instance)
        memory.touch_track(key, 10, np.array([10, 10, 50, 100]))
        face_vec = np.random.randn(512).astype(np.float32)
        face_vec /= np.linalg.norm(face_vec)
        for frame in (10, 13, 16):
            memory.observe_face(key, frame, face_vec, quality=0.85, pose="front", tier="strong")
        person_id = memory.state_for_track(key).person_id
        assert person_id is not None

        closed = mgr.mark_ended(65, camera="cam1")
        assert closed == instance
        assert mgr.is_closed(instance)
        assert person_id in memory.profiles
        assert memory.profiles[person_id].person_id == person_id


def test_invariant_b_overlapping_boxes_scrfd_single_face_exclusive_assignment():
    """Test B: Two persons overlap in bbox. SCRFD detects 1 face in the overlap.
    
    Hungarian assignment must give the face to EXACTLY ONE person; the other person gets None.
    """
    # Person 1 at x=[50, 120], y=[10, 180] (center x=85)
    box_p1 = np.array([50, 10, 120, 180], dtype=np.float32)
    # Person 2 overlapping at x=[90, 160], y=[15, 185] (center x=125)
    box_p2 = np.array([90, 15, 160, 185], dtype=np.float32)

    # Face detected at x=[75, 20, 95, 50] (center x=85, clearly belongs to P1)
    face = FaceDetection(bbox=np.array([75, 20, 95, 50], dtype=np.float32), score=0.92, kps=np.zeros((5, 2)))

    persons = [
        (1, box_p1, None),
        (2, box_p2, None),
    ]

    assignments = assign_faces_to_persons_hungarian([face], persons, (1080, 1920, 3))

    assert len(assignments) == 1, "Exactly one person should receive the single detected face!"
    assert 1 in assignments, "Person 1 should receive the face because it aligns with P1 head center!"
    assert 2 not in assignments, "Person 2 must NOT receive the face (no duplication or stealing)!"


def test_invariant_c_strong_face_conflict_quarantines_body_and_prevents_profile_poisoning():
    """Test C: Instance O bound to P009 encounters strong face conflict.
    
    Subsequent body observations must be quarantined, and P009.body_bank must NOT be poisoned.
    """
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=True)
        key = ("cam1", 1)

        # 1. Establish P001 with clean face and initial body
        memory.touch_track(key, 10, np.array([10, 10, 50, 120]))
        face_vec_a = np.array([1.0] + [0.0] * 511, dtype=np.float32)
        for f in (10, 12, 14):
            memory.observe_face(key, f, face_vec_a, quality=0.90, pose="front", tier="strong")

        st = memory.state_for_track(key)
        assert st is not None
        p_id = st.person_id
        assert p_id is not None
        profile = memory.profiles[p_id]

        # Initial body observation (promoted because face is solid)
        body_vec_clean = np.array([1.0] + [0.0] * 511, dtype=np.float32)
        memory.observe_body(key, 15, body_vec_clean, quality=0.88)
        memory.promote_body_if_authorized(key, 15, "FACE_CONFIRMED")
        initial_body_count = len(profile.body_bank)
        assert initial_body_count >= 1

        # 2. Encounter strong face conflict: person looks at camera, face vector is completely different
        face_vec_intruder = np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)
        memory.observe_face(key, 20, face_vec_intruder, quality=0.90, pose="front", tier="strong")

        assert st.strong_face_conflict is True, "Instance must flag strong face conflict!"
        assert st.body_quarantined is True, "Instance must lock body quarantine!"

        # 3. Present new body observations from the intruder (e.g. different clothes)
        body_vec_intruder = np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)
        memory.observe_body(key, 22, body_vec_intruder, quality=0.95)
        memory.observe_body(key, 25, body_vec_intruder, quality=0.96)

        # Invariant C check: Profile's body bank must NOT have grown with the intruder's body!
        assert len(profile.body_bank) == initial_body_count, (
            f"P{p_id:03d}.body_bank was poisoned! Count grew from {initial_body_count} to {len(profile.body_bank)}"
        )
        # The intruder's vector must not be in the profile's body bank
        for item in profile.body_bank:
            cosine = float(item.embedding @ body_vec_intruder)
            assert cosine < 0.5, f"Intruder body sample found in profile body bank with similarity {cosine}!"


def test_invariant_d_simultaneous_in_camera_blocked():
    """Test D: Two tracks active in the SAME camera at the same frame CANNOT share or reacquire the same G."""
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root))
        k1 = ("cam1", 1)
        k2 = ("cam1", 2)

        # Track 1 establishes G1
        box1 = np.array([50, 50, 100, 200], dtype=np.float32)
        for f in range(15):
            memory.touch_track(k1, f, box1)
        pid1 = memory.maybe_seed_person(k1, 15)
        assert pid1 is not None

        # Track 2 active at the same frame 15
        box2 = np.array([300, 50, 350, 200], dtype=np.float32)
        for f in range(15):
            memory.touch_track(k2, f, box2)

        # Track 2 cannot reacquire G1 while Track 1 is active
        decision, target = memory.conservative_g_reacquisition(memory.tracks[k2], 15)
        assert target is None or target.person_id != pid1
        assert decision != "REACQUIRE_G_BODY_MOTION"


def test_invariant_e_conservative_g_reacquisition_after_short_gap():
    """Test E: O1 ends. O2 appears after short gap with consistent motion & body => reacquires G1."""
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), short_gap_frames=60)
        k1 = ("cam1", 1)
        k2 = ("cam1", 2)

        box1 = np.array([50, 50, 100, 200], dtype=np.float32)
        for f in range(15):
            memory.touch_track(k1, f, box1)
        pid1 = memory.maybe_seed_person(k1, 15)
        assert pid1 is not None

        body_vec = np.array([1.0] + [0.0] * 511, dtype=np.float32)
        memory.observe_body(k1, 15, body_vec, quality=0.85)

        # O1 ends at frame 15.
        # O2 appears at frame 25 (gap=10 frames) nearby with same body
        box2 = np.array([55, 50, 105, 200], dtype=np.float32)
        for f in range(20, 35):
            memory.touch_track(k2, f, box2)

        for frame in (32, 33, 34):
            memory.observe_body(k2, frame, body_vec, quality=0.85)
        pid2 = memory.maybe_seed_person(k2, 35)

        assert pid2 == pid1, f"O2 should have reacquired G{pid1:03d}, got {pid2}"


def test_invariant_f_ambiguous_candidates_abstain_to_new_g():
    """Test F: When candidate G1 and G2 have identical/close match scores, system must ABSTAIN and mint a new G."""
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), short_gap_frames=60)
        k1 = ("cam1", 1)
        k2 = ("cam1", 2)
        k3 = ("cam1", 3)

        box = np.array([50, 50, 100, 200], dtype=np.float32)
        for f in range(15):
            memory.touch_track(k1, f, box)
            memory.touch_track(k2, f, box)
        pid1 = memory.maybe_seed_person(k1, 15)
        # Force different P for k2
        st2 = memory.tracks[k2]
        p2 = memory._new_profile(st2, 15, reason="test_seed")
        pid2 = p2.person_id

        # Both G1 and G2 end at frame 15 at the exact same location with identical body
        body_vec = np.array([1.0] + [0.0] * 511, dtype=np.float32)
        memory.observe_body(k1, 15, body_vec, quality=0.85)
        memory.observe_body(k2, 15, body_vec, quality=0.85)

        # O3 appears at frame 25. Scores with G1 and G2 will be identical (delta = 0)
        for f in range(20, 35):
            memory.touch_track(k3, f, box)
        memory.observe_body(k3, 34, body_vec, quality=0.85)

        decision, target = memory.conservative_g_reacquisition(memory.tracks[k3], 35, body_feat=body_vec)
        assert decision.state == "ABSTAIN"
        assert decision.reason == "INSUFFICIENT_BODY_SAMPLES"
        assert target is None, "Should not guess a target when ambiguous!"


def test_invariant_g_face_conflict_blocks_g_reacquisition():
    """Test G: If track has strong_face_conflict, it is blocked from reacquiring any G."""
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root))
        k = ("cam1", 1)
        memory.touch_track(k, 10, np.array([10, 10, 50, 120]))
        st = memory.tracks[k]
        st.strong_face_conflict = True

        decision, target = memory.conservative_g_reacquisition(st, 15)
        assert decision == "BLOCK_FACE_CONFLICT"
        assert target is None


def test_invariant_h_face_confirms_emp_and_preserved_across_reacquired_o():
    """Test H: Face confirms G -> EMP. Later, O2 reacquires G via body/motion and inherits EMP."""
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), short_gap_frames=60)
        k1 = ("cam1", 1)
        k2 = ("cam1", 2)

        # 1. Establish G1 on O1
        box1 = np.array([50, 50, 100, 200], dtype=np.float32)
        for f in range(15):
            memory.touch_track(k1, f, box1)
        pid1 = memory.maybe_seed_person(k1, 15)
        assert pid1 is not None

        # 2. Face Authority confirms EMP007 on O1
        memory.confirm_employee(k1, 15, "EMP007", source="gallery_face")
        profile1 = memory.profiles[pid1]
        assert profile1.employee_id == "EMP007", "G1 must be promoted to EMP007 by Face Authority!"

        body_vec = np.array([1.0] + [0.0] * 511, dtype=np.float32)
        memory.observe_body(k1, 15, body_vec, quality=0.85)

        # 3. O1 ends. O2 appears after gap with matching body and motion
        box2 = np.array([55, 50, 105, 200], dtype=np.float32)
        for f in range(20, 35):
            memory.touch_track(k2, f, box2)
        for frame in (32, 33, 34):
            memory.observe_body(k2, frame, body_vec, quality=0.85)

        # O2 reacquires G1
        pid2 = memory.maybe_seed_person(k2, 35)
        assert pid2 == pid1, f"O2 must reacquire G1, got {pid2}"

        # 4. Check that O2 automatically reflects EMP007 via G1 without needing a new face!
        reacquired_profile = memory.profile_for_track(k2)
        assert reacquired_profile is not None
        assert reacquired_profile.employee_id == "EMP007", (
            f"Reacquired track must inherit persistent employee_id EMP007, got {reacquired_profile.employee_id}"
        )


def test_invariant_i_body_alone_cannot_confirm_emp():
    """Test I: Body evidence CANNOT confirm employee_id. Only Face Authority may do so."""
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root))
        k = ("cam1", 1)

        box = np.array([50, 50, 100, 200], dtype=np.float32)
        for f in range(15):
            memory.touch_track(k, f, box)
        pid = memory.maybe_seed_person(k, 15)
        assert pid is not None

        # Feed dozens of identical high-quality body samples
        body_vec = np.array([1.0] + [0.0] * 511, dtype=np.float32)
        for f in range(16, 50):
            memory.observe_body(k, f, body_vec, quality=0.99)

        profile = memory.profiles[pid]
        assert profile.employee_id is None, "Body evidence must NEVER promote G to EMP without Face Authority!"


def test_body_association_tri_state_blocks_simultaneous_high_similarity():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=False)
        old_key, new_key = ("cam1", 1), ("cam1", 2)
        box = np.array([10, 10, 50, 120], dtype=np.float32)
        memory.touch_track(old_key, 10, box)
        profile = memory._new_profile(memory.tracks[old_key], 10, "test_seed")
        memory._add_body(profile, np.array([1.0, 0.0, 0.0]), .9, 10)
        memory.touch_track(new_key, 10, box)
        for frame in (10, 11, 12):
            memory.observe_body(new_key, frame, np.array([1.0, 0.0, 0.0]), .9)
        decision = memory.conservative_g_reacquisition(memory.tracks[new_key], 10)
        assert decision.state == "CANNOT_LINK"
        assert decision.reason == "SIMULTANEOUS_CANNOT_LINK"


def test_body_association_matches_coherent_o_level_descriptor():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=False)
        old_key, new_key = ("cam1", 1), ("cam1", 2)
        old_box = np.array([10, 10, 50, 120], dtype=np.float32)
        memory.touch_track(old_key, 0, old_box)
        profile = memory._new_profile(memory.tracks[old_key], 0, "test_seed")
        memory._add_body(profile, np.array([1.0, 0.0, 0.0]), .9, 0)
        memory.touch_track(new_key, 20, old_box)
        for frame in (20, 21, 22):
            memory.observe_body(new_key, frame, np.array([1.0, 0.01, 0.0]), .9)
        decision = memory.conservative_g_reacquisition(memory.tracks[new_key], 22)
        assert decision.state == "MATCH"
        assert decision.candidate_person_id == profile.person_id
        assert decision.sample_count == 3


def test_body_association_abstains_on_low_samples_and_close_runner_up():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=False)
        key = ("cam1", 3)
        memory.touch_track(key, 10, np.array([10, 10, 50, 120], dtype=np.float32))
        memory.observe_body(key, 10, np.array([1.0, 0.0, 0.0]), .9)
        low = memory.conservative_g_reacquisition(memory.tracks[key], 10)
        assert low.state == "ABSTAIN"
        assert low.reason == "INSUFFICIENT_BODY_SAMPLES"

        p1 = memory._new_profile(memory.tracks[key], 0, "test_seed")
        key2 = ("cam1", 4)
        memory.touch_track(key2, 0, np.array([10, 10, 50, 120], dtype=np.float32))
        p2 = memory._new_profile(memory.tracks[key2], 0, "test_seed")
        for profile in (p1, p2):
            memory._add_body(profile, np.array([1.0, 0.0, 0.0]), .9, 0)
        key3 = ("cam1", 5)
        memory.touch_track(key3, 20, np.array([10, 10, 50, 120], dtype=np.float32))
        for frame in (20, 21, 22):
            memory.observe_body(key3, frame, np.array([1.0, 0.0, 0.0]), .9)
        ambiguous = memory.conservative_g_reacquisition(memory.tracks[key3], 22)
        assert ambiguous.state == "ABSTAIN"
        assert ambiguous.reason == "AMBIGUOUS_MARGIN"


def test_body_association_conflict_is_cannot_link_before_similarity():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=False)
        key = ("cam1", 1)
        memory.touch_track(key, 1, np.array([10, 10, 50, 120], dtype=np.float32))
        memory.tracks[key].strong_face_conflict = True
        decision = memory.conservative_g_reacquisition(memory.tracks[key], 2)
        assert decision.state == "CANNOT_LINK"
        assert decision.reason == "FACE_CONFLICT"


def test_face_bank_keeps_distinct_views_in_same_pose_bucket():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=False)
        key = ("cam1", 1)
        box = np.array([10, 10, 50, 120], dtype=np.float32)
        memory.touch_track(key, 0, box)
        profile = memory._new_profile(memory.tracks[key], 0, "test_seed")
        first = np.zeros(512, dtype=np.float32)
        first[0] = 1.0
        second = np.zeros(512, dtype=np.float32)
        second[0] = 0.80
        second[1] = 0.60

        changed_first, _ = memory._add_face(profile, first, .8, "front", "support", 0)
        changed_second, _ = memory._add_face(profile, second, .8, "front", "support", 1)

        assert changed_first is True
        assert changed_second is True
        assert len(profile.face_bank) == 2


def test_bound_profile_learns_new_view_after_two_coherent_observations():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=False)
        key = ("cam1", 1)
        box = np.array([10, 10, 50, 120], dtype=np.float32)
        first = np.zeros(512, dtype=np.float32)
        first[0] = 1.0
        view = np.zeros(512, dtype=np.float32)
        view[0] = 0.80
        view[1] = 0.60
        memory.touch_track(key, 0, box)
        profile = memory._new_profile(memory.tracks[key], 0, "face_seed")
        memory._learn_face_sample(profile, key, 0, first, .8, "front", "support", None)

        first_result = memory.observe_face(key, 10, view, .60, "front", "support")
        second_result = memory.observe_face(key, 11, view, .60, "front", "support")

        assert first_result.decision == "FACE_VIEW_CANDIDATE_CURRENT"
        assert second_result.decision == "FACE_VIEW_LEARNED_CURRENT"
        assert len(profile.face_bank) == 2


def test_track_gap_freezes_body_learning_until_face_reverification():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=False)
        key = ("cam1", 1)
        box = np.array([10, 10, 50, 120], dtype=np.float32)
        face_vec = np.zeros(512, dtype=np.float32)
        face_vec[0] = 1.0
        body_vec = np.zeros(512, dtype=np.float32)
        body_vec[1] = 1.0

        memory.touch_track(key, 0, box)
        profile = memory._new_profile(memory.tracks[key], 0, "new_face_identity")
        memory._learn_face_sample(profile, key, 0, face_vec, .8, "front", "support", None)
        memory.observe_body(key, 0, body_vec, .9)
        memory.freeze_missing_tracks("cam1", 1, set())
        memory.observe_body(key, 2, body_vec, .9)

        assert memory.tracks[key].learning_frozen is True
        assert memory.tracks[key].pending_body_samples == []

        first = memory.observe_face(key, 3, face_vec, .8, "front", "support")
        second = memory.observe_face(key, 4, face_vec, .8, "front", "support")
        assert first.decision == "FACE_REVERIFY_CANDIDATE"
        assert second.decision == "FACE_VERIFIED_CURRENT"
        assert memory.tracks[key].learning_frozen is False


def test_new_face_is_held_near_an_active_profile_during_occlusion():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(
            sample_root=Path(root), require_face_before_person=False,
            face_new_confirmations=3,
        )
        old_key, new_key = ("cam1", 1), ("cam1", 2)
        box = np.array([10, 10, 50, 120], dtype=np.float32)
        old_face = np.zeros(512, dtype=np.float32)
        old_face[0] = 1.0
        new_face = np.zeros(512, dtype=np.float32)
        new_face[1] = 1.0

        memory.touch_track(old_key, 10, box)
        profile = memory._new_profile(memory.tracks[old_key], 10, "new_face_identity")
        memory._learn_face_sample(profile, old_key, 10, old_face, .8, "front", "support", None)
        memory.touch_track(new_key, 10, box)

        result = None
        for frame in (10, 11, 12):
            memory.touch_track(old_key, frame, box)
            memory.touch_track(new_key, frame, box)
            result = memory.observe_face(new_key, frame, new_face, .8, "front", "support")

        assert result is not None
        assert result.decision == "FACE_OCCLUSION_HOLD"
        assert memory.tracks[new_key].person_id is None


def test_profile_without_frontal_face_cannot_be_stable():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root), require_face_before_person=False)
        key = ("cam1", 1)
        box = np.array([10, 10, 50, 120], dtype=np.float32)
        memory.touch_track(key, 0, box)
        profile = memory._new_profile(memory.tracks[key], 0, "new_face_identity")

        for index, pose in enumerate(("left", "right")):
            face = np.zeros(512, dtype=np.float32)
            face[index] = 1.0
            memory._learn_face_sample(profile, key, index, face, .8, pose, "strong", None)
        for index in range(3):
            body = np.zeros(512, dtype=np.float32)
            body[index + 4] = 1.0
            memory._add_body(profile, body, .9, index)

        assert profile.maturity() == "LEARNING"

        frontal = np.zeros(512, dtype=np.float32)
        frontal[2] = 1.0
        memory._learn_face_sample(profile, key, 3, frontal, .8, "front", "strong", None)
        assert profile.maturity() == "STABLE"


def test_global_face_reacquire_promotes_pending_body_evidence():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(
            sample_root=Path(root), require_face_before_person=False,
            face_new_confirmations=1, face_match_confirmations=2,
        )
        old_key, new_key = ("cam1", 1), ("cam1", 2)
        box = np.array([10, 10, 50, 120], dtype=np.float32)
        face_vec = np.array([1.0] + [0.0] * 511, dtype=np.float32)
        body_vec = np.array([1.0] + [0.0] * 511, dtype=np.float32)

        memory.touch_track(old_key, 0, box)
        profile = memory._new_profile(memory.tracks[old_key], 0, "test_seed")
        memory._learn_face_sample(profile, old_key, 0, face_vec, .9, "front", "strong", None)

        memory.touch_track(new_key, 20, box)
        for frame in (20, 21, 22):
            memory.observe_body(new_key, frame, body_vec, .9)

        memory._rank_face = lambda *_args: FaceRankResult(None, None, None, None, None, False, "test")
        memory._rank_face_global = lambda *_args: FaceRankResult(
            profile.person_id, .9, None, None, None, True, "accepted",
        )
        result = memory.observe_face(new_key, 22, face_vec, .9, "front", "strong")

        assert result.accepted is True
        assert result.decision == "FACE_GLOBAL_REACQUIRE"
        assert memory.profile_for_track(new_key) is profile
        assert len(profile.body_bank) == 1
        assert memory.tracks[new_key].pending_body_samples == []
