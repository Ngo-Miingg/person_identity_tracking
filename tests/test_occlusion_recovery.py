from __future__ import annotations

import json

import numpy as np

from src.occlusion_recovery import OcclusionRecoveryManager, TrackObservation, top3_median_similarity


def box(x: float, y: float = 10.0) -> np.ndarray:
    return np.array([x, y, x + 20.0, y + 100.0], dtype=np.float32)


def test_top3_median_is_not_maximum_similarity():
    clean = [np.array([1.0, 0.0]), np.array([0.99, 0.1]), np.array([0.0, 1.0])]
    new = [np.array([1.0, 0.0])]
    value = top3_median_similarity(clean, new)
    assert value is not None
    assert value < 1.0


def test_shadow_links_only_after_two_by_two_clean_recovery(tmp_path):
    events = tmp_path / "occlusion_events.jsonl"
    manager = OcclusionRecoveryManager(events, min_post_frames=2)
    manager.step(0, [TrackObservation(1, box(0)), TrackObservation(2, box(100))])
    manager.add_embedding(0, 1, np.array([1.0, 0.0]))
    manager.add_embedding(0, 2, np.array([0.0, 1.0]))
    manager.step(1, [TrackObservation(1, box(15)), TrackObservation(2, box(85))])
    manager.step(2, [TrackObservation(1, box(35)), TrackObservation(2, box(65))])
    manager.step(3, [])
    manager.step(4, [TrackObservation(7, box(70)), TrackObservation(8, box(30))])
    manager.add_embedding(4, 7, np.array([0.0, 1.0]))
    manager.add_embedding(4, 8, np.array([1.0, 0.0]))
    manager.step(5, [TrackObservation(7, box(75)), TrackObservation(8, box(25))])
    manager.add_embedding(5, 7, np.array([0.0, 1.0]))
    manager.add_embedding(5, 8, np.array([1.0, 0.0]))
    data = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    assert data and data[-1]["runtime_applied"] is False
    assert data[-1]["proposed_decision"] in {"LINK", "ABSTAIN"}
    assert all(item["L"] in {1, 2} for item in data[-1]["old_tracks"])
    assert all(item["L"] in {7, 8} for item in data[-1]["new_tracks"])


def test_three_person_event_is_not_eligible(tmp_path):
    events = tmp_path / "occlusion_events.jsonl"
    manager = OcclusionRecoveryManager(events)
    manager.step(0, [TrackObservation(1, box(0)), TrackObservation(2, box(25)), TrackObservation(3, box(50))])
    payload = json.loads(events.read_text(encoding="utf-8").splitlines()[0])
    assert payload["proposed_decision"] == "ABSTAIN"
    assert payload["eligible"] is False
