from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from src.person_memory import PersonMemory


def _body(value: int) -> np.ndarray:
    vector = np.zeros(512, dtype=np.float32)
    vector[value] = 1.0
    return vector


def test_case_1_unbound_body_stays_on_o():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root))
        key = ("cam1", 1)
        for frame in range(20):
            memory.touch_track(key, frame, np.array([10, 10, 50, 120]))
            memory.observe_body(key, frame, _body(0), 0.9)
        assert memory.profiles == {}
        assert len(memory.tracks[key].pending_body_samples) == 15


def test_case_2_face_authority_explicitly_promotes_body_prototypes():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root))
        key = ("cam1", 1)
        memory.touch_track(key, 1, np.array([10, 10, 50, 120]))
        for i in range(10):
            memory.observe_body(key, i + 1, _body(i), 0.9)
        st = memory.tracks[key]
        profile = memory._new_profile(st, 20, "new_face_identity")
        assert len(profile.body_bank) == 0
        promoted = memory.promote_body_if_authorized(key, 20, "NEW_FACE_IDENTITY")
        assert promoted > 0
        assert 0 < len(profile.body_bank) <= 8


def test_case_3_body_only_reacquire_cannot_promote():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root))
        key = ("cam1", 1)
        memory.touch_track(key, 1, np.array([10, 10, 50, 120]))
        profile = memory._new_profile(memory.tracks[key], 1, "test_seed")
        memory._add_body(profile, _body(0), 0.9, 1)
        key2 = ("cam1", 2)
        memory.touch_track(key2, 2, np.array([10, 10, 50, 120]))
        memory.observe_body(key2, 2, _body(0), 0.9)
        memory._bind(memory.tracks[key2], profile, 3, "short_gap_motion_body", reacquire=True)
        before = len(profile.body_bank)
        assert memory.promote_body_if_authorized(key2, 3, "BODY_REACQUIRE") == 0
        assert len(profile.body_bank) == before


def test_case_4_face_conflict_locks_promotion_but_keeps_audit_samples():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root))
        key = ("cam1", 1)
        memory.touch_track(key, 1, np.array([10, 10, 50, 120]))
        profile = memory._new_profile(memory.tracks[key], 1, "new_face_identity")
        memory.observe_body(key, 2, _body(0), 0.9)
        st = memory.tracks[key]
        st.strong_face_conflict = True
        st.body_quarantined = True
        st.body_quarantine_reason = "FACE_UNKNOWN_CONFLICT_HOLD_P"
        before = len(profile.body_bank)
        memory.observe_body(key, 3, _body(1), 0.9)
        assert st.body_quarantined is True
        assert memory.promote_body_if_authorized(key, 3, "FACE_CONFIRMED") == 0
        assert len(profile.body_bank) == before
        assert len(st.pending_body_samples) == 2


def test_case_5_reused_o_has_isolated_pending_body():
    with tempfile.TemporaryDirectory() as root:
        memory = PersonMemory(sample_root=Path(root))
        old_key = ("cam1", 1)
        new_key = ("cam1", 2)
        memory.observe_body(old_key, 1, _body(0), 0.9)
        memory.observe_body(new_key, 2, _body(1), 0.9)
        old_pending = memory.tracks[old_key].pending_body_samples
        new_pending = memory.tracks[new_key].pending_body_samples
        assert len(old_pending) == len(new_pending) == 1
        assert not np.array_equal(old_pending[0]["embedding"], new_pending[0]["embedding"])
