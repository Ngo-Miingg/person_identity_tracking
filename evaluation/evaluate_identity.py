import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def calculate_iou(box_a: list[float], box_b: list[float]) -> float:
    xa = max(box_a[0], box_b[0])
    ya = max(box_a[1], box_b[1])
    xb = min(box_a[2], box_b[2])
    yb = min(box_a[3], box_b[3])
    inter = max(0.0, xb - xa) * max(0.0, yb - ya)
    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return float(inter / union)


def evaluate_run(
    ground_truth_path: str | Path,
    tracks_csv_path: str | Path,
    iou_threshold: float = 0.5,
    occlusion_events_path: str | Path | None = None,
) -> dict[str, Any]:
    gt_file = Path(ground_truth_path)
    pred_file = Path(tracks_csv_path)

    if not gt_file.is_file():
        raise FileNotFoundError(f"Ground truth file missing: {gt_file}")
    if not pred_file.is_file():
        raise FileNotFoundError(f"Predicted tracks.csv missing: {pred_file}")

    with gt_file.open("r", encoding="utf-8") as f:
        gt_data = json.load(f)

    # Index ground truth by frame
    gt_by_frame: dict[int, list[dict[str, Any]]] = defaultdict(list)
    all_gt_persons = set()
    all_gt_employees = set()
    for frame_entry in gt_data.get("annotations", []):
        f_idx = frame_entry["frame"]
        for p in frame_entry.get("persons", []):
            gt_by_frame[f_idx].append(p)
            all_gt_persons.add(p["gt_id"])
            if p.get("employee_id"):
                all_gt_employees.add(p["employee_id"])

    # Read prediction tracks.csv
    pred_by_frame: dict[int, list[dict[str, Any]]] = defaultdict(list)
    with pred_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            f_idx = int(row["frame"])
            pred_by_frame[f_idx].append({
                "track_id": int(row["track_id"]),
                "person_id": row.get("person_id") or None,
                "identity_state": row.get("identity_state") or "UNKNOWN",
                # Inference exports the gallery employee label as `identity`.
                # Keep employee_id as a compatibility fallback for older CSVs.
                "employee_id": row.get("identity") or row.get("employee_id") or None,
                "bbox": [float(row["x1"]), float(row["y1"]), float(row["x2"]), float(row["y2"])],
            })

    def gt_for_track(track_id: int, frame: int) -> str | None:
        # Evaluate an O-link at the event boundary without changing inference state.
        candidates = pred_by_frame.get(frame, [])
        matches = [item for item in candidates if item["track_id"] == track_id]
        if not matches:
            return None
        best = max(matches, key=lambda item: item["bbox"][2] - item["bbox"][0])
        gt_items = gt_by_frame.get(frame, [])
        scored = [(calculate_iou(gt["bbox"], best["bbox"]), gt["gt_id"]) for gt in gt_items]
        scored = [item for item in scored if item[0] >= iou_threshold]
        return max(scored, default=(0.0, None))[1]

    # Trajectory mappings over time
    # gt_id -> list of (frame, matched_track_id, matched_person_id, matched_employee_id)
    gt_trajectories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # Tracklet ID -> set of gt_ids (for merge detection)
    person_id_to_gt_ids: dict[str, set[str]] = defaultdict(set)
    gt_id_to_person_ids: dict[str, set[str]] = defaultdict(set)

    matched_frames_count = 0
    unmatched_gt_count = 0

    all_frames = sorted(set(gt_by_frame.keys()))
    for f_idx in all_frames:
        gt_persons = gt_by_frame[f_idx]
        pred_items = pred_by_frame.get(f_idx, [])

        matched_preds = set()
        for gt in gt_persons:
            best_iou = 0.0
            best_pred = None
            for p_idx, pred in enumerate(pred_items):
                if p_idx in matched_preds:
                    continue
                iou = calculate_iou(gt["bbox"], pred["bbox"])
                if iou >= iou_threshold and iou > best_iou:
                    best_iou = iou
                    best_pred = (p_idx, pred)

            if best_pred:
                p_idx, pred = best_pred
                matched_preds.add(p_idx)
                matched_frames_count += 1
                pid = pred["person_id"]
                emp = pred["employee_id"]
                gt_trajectories[gt["gt_id"]].append({
                    "frame": f_idx,
                    "iou": best_iou,
                    "track_id": pred["track_id"],
                    "person_id": pid,
                    "employee_id": emp,
                    "gt_employee_id": gt.get("employee_id"),
                })
                if pid:
                    person_id_to_gt_ids[pid].add(gt["gt_id"])
                    gt_id_to_person_ids[gt["gt_id"]].add(pid)
            else:
                unmatched_gt_count += 1

    # Metric 1: Tracker Fragmentation (Tracker ID switches per GT person)
    tracker_switches = 0
    for gt_id, traj in gt_trajectories.items():
        distinct_track_ids = {item["track_id"] for item in traj}
        if len(distinct_track_ids) > 1:
            tracker_switches += (len(distinct_track_ids) - 1)

    # Metric 2: Persistent Identity Switches (Person ID transitions within single GT person)
    persistent_id_switches = 0
    for gt_id, traj in gt_trajectories.items():
        last_pid = None
        for item in traj:
            pid = item["person_id"]
            if pid is not None:
                if last_pid is not None and pid != last_pid:
                    persistent_id_switches += 1
                last_pid = pid

    # Metric 3: False Merges (multiple distinct GT persons assigned to the same persistent person_id)
    false_merges = (
        sum(1 for pid, gts in person_id_to_gt_ids.items() if len(gts) > 1)
        if len(all_gt_persons) >= 2
        else None
    )

    # Metric 4: False Splits (single GT person split across multiple persistent person_ids)
    false_splits = sum(max(0, len(pids) - 1) for gt_id, pids in gt_id_to_person_ids.items())

    # Metric 5: False Positive Identification Rate (FPIR)
    # Evaluates how often an un-enrolled person (GT employee_id is None) is assigned an employee ID
    unknown_observations_total = 0
    unknown_incorrectly_promoted = 0
    for gt_id, traj in gt_trajectories.items():
        for item in traj:
            if item["gt_employee_id"] is None:
                unknown_observations_total += 1
                if item["employee_id"] is not None:
                    unknown_incorrectly_promoted += 1

    fpir_rate = (unknown_incorrectly_promoted / unknown_observations_total) if unknown_observations_total > 0 else 0.0

    # Metric 6: Employee False Negative Rate (FNIR)
    employee_observations_total = 0
    employee_missed = 0
    for gt_id, traj in gt_trajectories.items():
        for item in traj:
            if item["gt_employee_id"] is not None:
                employee_observations_total += 1
                if item["employee_id"] != item["gt_employee_id"]:
                    employee_missed += 1

    fnir_rate = (employee_missed / employee_observations_total) if employee_observations_total > 0 else 0.0

    recovery = {
        "eligible_events": 0,
        "correct_recovery": 0,
        "wrong_recovery": 0,
        "abstain": 0,
        "precision": 0.0,
        "coverage": 0.0,
        "runtime_applied_violations": 0,
        "contaminated_shadow_updates": 0,
    }
    events_path = Path(occlusion_events_path) if occlusion_events_path else pred_file.parent / "live" / "occlusion_events.jsonl"
    if events_path.is_file():
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("runtime_applied") is not False:
                    recovery["runtime_applied_violations"] += 1
                if event.get("contaminated_shadow_update", False):
                    recovery["contaminated_shadow_updates"] += 1
                if not event.get("eligible", False):
                    continue
                recovery["eligible_events"] += 1
                if event.get("proposed_decision") != "LINK":
                    recovery["abstain"] += 1
                    continue
                links = event.get("proposed_links", [])
                correct = len(links) == 2 and all(
                    len(link) == 2
                    and gt_for_track(int(next(item["L"] for item in event["old_tracks"] if item["O"] == link[0])), event["frame_start"]) is not None
                    and gt_for_track(int(next(item["L"] for item in event["new_tracks"] if item["O"] == link[1])), event["frame_decision"]) == gt_for_track(int(next(item["L"] for item in event["old_tracks"] if item["O"] == link[0])), event["frame_start"])
                    for link in links
                )
                if correct:
                    recovery["correct_recovery"] += 1
                else:
                    recovery["wrong_recovery"] += 1
        denominator = recovery["correct_recovery"] + recovery["wrong_recovery"]
        recovery["precision"] = recovery["correct_recovery"] / denominator if denominator else 0.0
        recovery["coverage"] = denominator / recovery["eligible_events"] if recovery["eligible_events"] else 0.0

    report = {
        "dataset": gt_data.get("dataset", "unknown"),
        "total_gt_frames": len(all_frames),
        "unique_gt_persons": len(all_gt_persons),
        "unique_gt_employees": len(all_gt_employees),
        "matched_detections": matched_frames_count,
        "unmatched_gt_detections": unmatched_gt_count,
        "tracker_fragmentation_switches": tracker_switches,
        "persistent_identity_switches": persistent_id_switches,
        "false_merges": false_merges,
        "false_splits": false_splits,
        "fpir": {
            "rate": round(fpir_rate, 4),
            "false_promotions": unknown_incorrectly_promoted,
            "total_unknown_observations": unknown_observations_total,
        },
        "fnir": {
            "rate": round(fnir_rate, 4),
            "missed_employees": employee_missed,
            "total_employee_observations": employee_observations_total,
        },
        "occlusion_recovery": recovery,
    }

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gt", required=True, help="Path to ground truth JSON file")
    parser.add_argument("--tracks", required=True, help="Path to output tracks.csv")
    parser.add_argument("--out", default="evaluation/reports/evaluation_report.json")
    parser.add_argument("--occlusion-events", default=None)
    args = parser.parse_args()

    results = evaluate_run(args.gt, args.tracks, occlusion_events_path=args.occlusion_events)
    print(json.dumps(results, indent=2))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
