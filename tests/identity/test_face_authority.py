import unittest
import numpy as np
import tempfile
from pathlib import Path

from src.evidence_fusion import TrackletEvidenceFusion, IdentityEvidence
from src.identity_manager import IdentityManager
from src.gallery import GalleryHit
from src.person_memory import PersonMemory
from src.face_quality import estimate_pose


class TestFaceAuthority(unittest.TestCase):
    """Adversarial verification of Face-as-Sole-Authority architectural invariants."""

    def setUp(self):
        self.fusion = TrackletEvidenceFusion(
            face_threshold=0.56,
            weak_face_threshold=0.45,
            body_threshold=0.84,
            margin=0.04,
        )
        self.ident_mgr = IdentityManager(
            min_confirmations=3,
            min_confirmation_weight=1.45,
            min_support_quality=0.32,
            strong_quality=0.68,
        )

    def test_e1_body_only_cannot_confirm_employee(self):
        """Scenario E1: Very high body similarity alone MUST NOT produce CONFIRMED status."""
        body_only_evidence = IdentityEvidence(
            identity_id=101,
            face_scores=[],  # No face visible
            body_scores=[0.98, 0.96, 0.97],
            face_support=0,
            body_support=5,
        )
        decision = self.fusion.decide([body_only_evidence])
        self.assertNotEqual(decision.state, "CONFIRMED", "Violation: Body alone promoted identity to CONFIRMED!")
        self.assertEqual(decision.state, "PROVISIONAL", "Body-only evidence must remain strictly PROVISIONAL.")
        self.assertEqual(decision.reason, "BODY_ONLY_PROVISIONAL")

    def test_e2_face_authority_overrides_conflicting_body(self):
        """Scenario E2: When Face indicates Candidate A and Body indicates Candidate B, Face MUST win."""
        cand_a_face = IdentityEvidence(
            identity_id=1,  # Person 1 (Face matched)
            face_scores=[0.82, 0.85],
            body_scores=[],
            face_support=2,
            body_support=0,
        )
        cand_b_body = IdentityEvidence(
            identity_id=2,  # Person 2 (Body matched clothes)
            face_scores=[],
            body_scores=[0.92, 0.90, 0.91],
            face_support=0,
            body_support=4,
        )
        decision = self.fusion.decide([cand_a_face, cand_b_body])
        self.assertEqual(decision.identity_id, 1, "Violation: Conflicting body candidate overrode face authority!")
        self.assertEqual(decision.state, "CONFIRMED")
        self.assertEqual(decision.reason, "FACE_ONLY")

    def test_e3_identity_manager_requires_multi_frame_confirmations(self):
        """Scenario E3: A single frame match cannot immediately confirm an employee."""
        hit = GalleryHit(
            name="EMP001", score=0.75, second_score=0.50, margin=0.20,
            accepted=True, threshold=0.55, margin_threshold=0.07
        )
        # Frame 1: first observation (tier="support", quality=0.50) -> CANDIDATE
        st1 = self.ident_mgr.update(track_id=1, frame=0, hit=hit, quality=0.50, tier="support")
        self.assertEqual(st1.state, "CANDIDATE")
        self.assertIsNone(st1.employee_id)

        # Frame 2: second observation with support tier -> still CANDIDATE (requires 3 votes)
        st2 = self.ident_mgr.update(track_id=1, frame=1, hit=hit, quality=0.50, tier="support")
        self.assertEqual(st2.state, "CANDIDATE")
        self.assertIsNone(st2.employee_id)

        # Frame 3: third observation -> threshold reached (weight 1.50 >= 1.45, votes 3 >= 3)
        st3 = self.ident_mgr.update(track_id=1, frame=2, hit=hit, quality=0.50, tier="support")
        self.assertEqual(st3.state, "CONFIRMED")
        self.assertEqual(st3.employee_id, "EMP001")

        # Fast-path verification: strong tier (quality=0.80 >= 0.68) can confirm in 2 frames
        mgr_fast = IdentityManager(min_confirmations=3, min_confirmation_weight=1.45)
        st_fast1 = mgr_fast.update(track_id=2, frame=0, hit=hit, quality=0.80, tier="strong")
        self.assertEqual(st_fast1.state, "CANDIDATE")
        st_fast2 = mgr_fast.update(track_id=2, frame=1, hit=hit, quality=0.80, tier="strong")
        self.assertEqual(st_fast2.state, "CONFIRMED")
        self.assertEqual(st_fast2.employee_id, "EMP001")

    def test_e4_weak_or_rejected_face_cannot_change_identity(self):
        """Scenario E4: Rejected or poor quality face does not alter confirmed identity."""
        hit1 = GalleryHit(
            name="EMP001", score=0.75, second_score=0.50, margin=0.20,
            accepted=True, threshold=0.55, margin_threshold=0.07
        )
        for f in range(3):
            self.ident_mgr.update(track_id=1, frame=f, hit=hit1, quality=0.50, tier="support")
        self.assertEqual(self.ident_mgr.states[1].employee_id, "EMP001")

        # Weak face claiming EMP002 with tier "reject"
        hit2 = GalleryHit(
            name="EMP002", score=0.60, second_score=0.40, margin=0.10,
            accepted=True, threshold=0.55, margin_threshold=0.07
        )
        st = self.ident_mgr.update(track_id=1, frame=10, hit=hit2, quality=0.15, tier="reject")
        self.assertEqual(st.employee_id, "EMP001", "Violation: Rejected face changed confirmed employee ID!")
        self.assertEqual(st.conflict_streak, 0)

    def test_weak_gallery_faces_cannot_confirm_employee(self):
        """Weak detections may be logged, but cannot become identity evidence."""
        hit = GalleryHit(
            name="EMP001", score=0.80, second_score=0.40, margin=0.40,
            accepted=True, threshold=0.55, margin_threshold=0.07,
        )
        for frame in range(10):
            state = self.ident_mgr.update(1, frame, hit, quality=0.44, tier="weak")
        self.assertEqual(state.state, "UNIDENTIFIED")
        self.assertIsNone(state.employee_id)

    def test_gallery_votes_expire_after_long_gap(self):
        hit = GalleryHit("EMP001", .80, .40, .40, True, .55, .07)
        manager = IdentityManager(min_confirmations=3, max_vote_gap=4)
        manager.update(1, 0, hit, .6, "support")
        manager.update(1, 1, hit, .6, "support")
        state = manager.update(1, 20, hit, .6, "support")
        self.assertEqual(state.candidate_votes, 1)
        self.assertNotEqual(state.state, "CONFIRMED")

    def test_e5_ambiguity_flag_freezes_body_learning(self):
        """Scenario E5: When ambiguous=True (IoU >= 0.50), body embeddings are frozen."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = PersonMemory(
                sample_root=Path(tmpdir),
                ambiguity_grace_frames=8,
                body_learn_quality=0.35,
                new_person_after_frames=1,
                require_face_before_person=False,
            )
            key = ("cam0", 1)
            box = np.array([100.0, 100.0, 200.0, 300.0])
            memory.touch_track(key, frame=0, bbox=box, ambiguous=False)
            memory.touch_track(key, frame=1, bbox=box, ambiguous=False)

            # Seed a person profile
            pid = memory.maybe_seed_person(key, frame=1)
            self.assertIsNotNone(pid, "Track should seed a profile when require_face_before_person=False")
            profile = memory.profiles[pid]

            # Add body observation under nominal condition
            body_vec_1 = np.random.randn(512).astype(np.float32)
            body_vec_1 /= np.linalg.norm(body_vec_1)
            memory.observe_body(key, frame=2, embedding=body_vec_1, quality=0.85, ambiguous=False)
            initial_body_count = profile.body_observations
            self.assertEqual(initial_body_count, 0)
            self.assertEqual(len(memory.state_for_track(key).pending_body_samples), 1)

            # Enter AMBIGUITY interval (e.g. crossing)
            memory.touch_track(key, frame=3, bbox=box, ambiguous=True)
            body_vec_crossing = np.random.randn(512).astype(np.float32)
            body_vec_crossing /= np.linalg.norm(body_vec_crossing)
            memory.observe_body(key, frame=3, embedding=body_vec_crossing, quality=0.90, ambiguous=True)

            # The body observation count in profile reservoir must NOT have increased!
            self.assertEqual(
                profile.body_observations,
                initial_body_count,
                "CRITICAL VIOLATION: Body learning updated during crossing ambiguity interval!"
            )

    def test_e6_yaw_proxy_strict_boundary(self):
        """Scenario E6: Yaw proxy mathematical boundaries: < -0.25 (left), > 0.25 (right), [-0.25, 0.25] (front)."""
        # 5 canonical landmarks: left_eye, right_eye, nose, left_mouth, right_mouth
        base_landmarks = np.array([
            [100.0, 100.0],  # left eye
            [140.0, 100.0],  # right eye (midpoint = (120, 100), eye_dist = 40, half_eye_dist = 20)
            [120.0, 120.0],  # nose (dx = 0 -> yaw = 0.0)
            [105.0, 140.0],  # left mouth
            [135.0, 140.0],  # right mouth
        ], dtype=np.float32)

        # Yaw = 0.0 -> front
        pose_front = estimate_pose(base_landmarks)
        self.assertEqual(pose_front.label, "front")
        self.assertAlmostEqual(pose_front.yaw_proxy, 0.0, places=2)

        # Move nose to left: dx = -6.0 -> yaw = -6.0 / 20 = -0.30 (< -0.25) -> left
        lm_left = base_landmarks.copy()
        lm_left[2, 0] = 114.0
        pose_left = estimate_pose(lm_left)
        self.assertEqual(pose_left.label, "left")
        self.assertLess(pose_left.yaw_proxy, -0.25)

        # Move nose to right: dx = +6.0 -> yaw = +6.0 / 20 = +0.30 (> 0.25) -> right
        lm_right = base_landmarks.copy()
        lm_right[2, 0] = 126.0
        pose_right = estimate_pose(lm_right)
        self.assertEqual(pose_right.label, "right")
        self.assertGreater(pose_right.yaw_proxy, 0.25)


if __name__ == "__main__":
    unittest.main()
