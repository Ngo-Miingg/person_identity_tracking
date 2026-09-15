import unittest
import numpy as np
import tempfile
from pathlib import Path

from src.person_memory import PersonMemory
from src.identity_manager import IdentityManager
from src.gallery import GalleryHit
from src.infer_engine import _ambiguity_flags


class TestAdversarialScenarios(unittest.TestCase):
    """Adversarial validation of complex multi-person identity tracking scenarios."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.memory = PersonMemory(
            sample_root=Path(self.tmpdir.name),
            ambiguity_grace_frames=8,
            face_match_threshold=0.56,
            face_match_margin=0.04,
            body_learn_quality=0.35,
            new_person_after_frames=2,
            require_face_before_person=False,
            max_body_views=8,
            max_face_per_pose=4,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_d4_crossing_iou_detection(self):
        """Scenario D4: Verify IoU >= 0.50 and IoS >= 0.75 correctly trigger ambiguity flags."""
        boxes = np.array([
            [100.0, 100.0, 200.0, 200.0],
            [130.0, 100.0, 230.0, 200.0],
        ])
        flags = _ambiguity_flags(boxes)
        self.assertTrue(flags[0], "Box A must be flagged as ambiguous when IoU >= 0.50")
        self.assertTrue(flags[1], "Box B must be flagged as ambiguous when IoU >= 0.50")

        # Non-overlapping boxes:
        clear_boxes = np.array([
            [100.0, 100.0, 200.0, 200.0],
            [300.0, 100.0, 400.0, 200.0],
        ])
        clear_flags = _ambiguity_flags(clear_boxes)
        self.assertFalse(clear_flags[0])
        self.assertFalse(clear_flags[1])

    def test_d6_similar_clothing_cannot_steal_employee_identity(self):
        """Scenario D6: Person B with identical clothes to EMP001 must NOT inherit EMP001."""
        ident_mgr = IdentityManager(min_confirmations=3)

        hit_emp = GalleryHit("EMP001", 0.78, 0.40, 0.25, True, 0.55, 0.07)
        for f in range(3):
            ident_mgr.update(track_id=1, frame=f, hit=hit_emp, quality=0.75, tier="support")
        self.assertEqual(ident_mgr.states[1].employee_id, "EMP001")

        st_track2 = ident_mgr.ensure(track_id=2, frame=10)
        self.assertIsNone(st_track2.employee_id)
        self.assertEqual(st_track2.state, "UNIDENTIFIED")

    def test_d11_unknown_person_stays_unidentified_without_gallery(self):
        """Scenario D11: Unknown person never confirmed as employee when not in gallery."""
        ident_mgr = IdentityManager()
        hit_none = GalleryHit(None, 0.32, 0.20, 0.02, False, 0.55, 0.07)
        for f in range(10):
            st = ident_mgr.update(track_id=5, frame=f, hit=hit_none, quality=0.80, tier="strong")
        self.assertIsNone(st.employee_id)
        self.assertEqual(st.state, "UNIDENTIFIED")

    def test_d14_employee_plus_unknown_crossing_protection(self):
        """Scenario D14: After crossing, Unknown person does not absorb Employee identity."""
        key_emp = ("cam0", 1)
        key_unk = ("cam0", 2)
        box_a = np.array([100.0, 100.0, 200.0, 300.0])
        box_b = np.array([110.0, 100.0, 210.0, 300.0])

        for f in range(3):
            self.memory.touch_track(key_emp, frame=f, bbox=box_a, ambiguous=False)
            self.memory.touch_track(key_unk, frame=f, bbox=box_b, ambiguous=False)

        pid_emp = self.memory.maybe_seed_person(key_emp, frame=2)
        pid_unk = self.memory.maybe_seed_person(key_unk, frame=2)
        self.assertIsNotNone(pid_emp)
        self.assertIsNotNone(pid_unk)
        self.assertNotEqual(pid_emp, pid_unk)

        self.memory.confirm_employee(key_emp, frame=2, employee_id="EMP001", source="gallery")
        self.assertEqual(self.memory.profiles[pid_emp].employee_id, "EMP001")
        self.assertIsNone(self.memory.profiles[pid_unk].employee_id)

        overlap_boxes = np.array([box_a, box_b])
        ambig_flags = _ambiguity_flags(overlap_boxes)
        self.assertTrue(all(ambig_flags))

        for f in range(3, 10):
            self.memory.touch_track(key_emp, frame=f, bbox=box_a, ambiguous=True)
            self.memory.touch_track(key_unk, frame=f, bbox=box_b, ambiguous=True)

        self.assertEqual(self.memory.profiles[pid_emp].employee_id, "EMP001")
        self.assertIsNone(self.memory.profiles[pid_unk].employee_id, "Violation: Unknown person inherited employee identity during crossing!")

    def test_employee_cannot_be_confirmed_on_two_active_tracks(self):
        """A simultaneous duplicate employee claim is blocked per camera."""
        first = ("cam0", 1)
        second = ("cam0", 2)
        box_a = np.array([0.0, 0.0, 80.0, 160.0])
        box_b = np.array([300.0, 0.0, 380.0, 160.0])
        for key, box in ((first, box_a), (second, box_b)):
            self.memory.touch_track(key, frame=5, bbox=box, ambiguous=False)
            self.memory.maybe_seed_person(key, frame=5)
        self.memory.confirm_employee(first, frame=5, employee_id="EMP001", source="test")
        self.memory.confirm_employee(second, frame=5, employee_id="EMP001", source="test")
        employee_profiles = [p for p in self.memory.profiles.values() if p.employee_id == "EMP001"]
        self.assertEqual(len(employee_profiles), 1)

    def test_f1_memory_contamination_vector_freeze(self):
        """Scenario F1: Prototype vector array before vs after ambiguity interval must be strictly identical."""
        key = ("cam0", 1)
        box = np.array([100.0, 100.0, 200.0, 300.0])
        for f in range(3):
            self.memory.touch_track(key, frame=f, bbox=box, ambiguous=False)
        pid = self.memory.maybe_seed_person(key, frame=2)
        profile = self.memory.profiles[pid]

        # Learn 3 nominal body samples
        for f in range(3):
            v = np.random.randn(512).astype(np.float32)
            v /= np.linalg.norm(v)
            self.memory.observe_body(key, frame=f+3, embedding=v, quality=0.85, ambiguous=False)
        # Snapshot prototypes before crossing
        protos_before = [np.copy(m.embedding) for m in profile.body_bank if m.embedding is not None]
        self.assertEqual(len(protos_before), 0)
        self.assertEqual(len(self.memory.state_for_track(key).pending_body_samples), 3)

        # Inject 10 adversarial/crossing body vectors with ambiguous=True
        for f in range(10):
            v_bad = np.random.randn(512).astype(np.float32)
            v_bad /= np.linalg.norm(v_bad)
            self.memory.touch_track(key, frame=f+10, bbox=box, ambiguous=True)
            self.memory.observe_body(key, frame=f+10, embedding=v_bad, quality=0.99, ambiguous=True)

        # Snapshot prototypes after crossing
        protos_after = [np.copy(m.embedding) for m in profile.body_bank if m.embedding is not None]
        self.assertEqual(len(protos_before), len(protos_after), "Reservoir size must not change during ambiguity!")
        for b_arr, a_arr in zip(protos_before, protos_after):
            np.testing.assert_array_equal(b_arr, a_arr, "Prototypes were contaminated during ambiguity interval!")

    def test_f4_reservoir_size_caps(self):
        """Scenario F4: Memory reservoir must strictly obey size caps (max_body_views=8)."""
        key = ("cam0", 7)
        box = np.array([50.0, 50.0, 150.0, 250.0])
        for f in range(3):
            self.memory.touch_track(key, frame=f, bbox=box, ambiguous=False)
        pid = self.memory.maybe_seed_person(key, frame=2)
        profile = self.memory.profiles[pid]

        # Push 30 distinct body vectors
        for f in range(30):
            v = np.random.randn(512).astype(np.float32)
            v /= np.linalg.norm(v)
            self.memory.observe_body(key, frame=f+3, embedding=v, quality=0.90, ambiguous=False)

        # Body views must be capped at max_body_views = 8
        self.assertLessEqual(len(profile.body_bank), 8, "Reservoir exceeded max_body_views cap!")


if __name__ == "__main__":
    unittest.main()
