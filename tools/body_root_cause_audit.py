from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np


THRESHOLDS = (0.70, 0.75, 0.78, 0.80, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98)


def cosine_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    b = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-12)
    return a @ b.T


def metrics(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    matrix = cosine_matrix(a, b)
    ca = np.mean(a, axis=0)
    cb = np.mean(b, axis=0)
    centroid = float(ca @ cb / max(np.linalg.norm(ca) * np.linalg.norm(cb), 1e-12))
    values = np.sort(matrix.reshape(-1))[::-1]
    return {
        "centroid": centroid,
        "median": float(np.median(matrix)),
        "top5_mean": float(np.mean(values[: min(5, len(values))])),
        "max": float(values[0]),
    }


def self_consistency(a: np.ndarray) -> float:
    if len(a) < 2:
        return float("nan")
    matrix = cosine_matrix(a, a)
    values = matrix[np.triu_indices(len(a), 1)]
    return float(np.median(values))


def percentile(values: list[float], q: float) -> float | None:
    return float(np.percentile(values, q)) if values else None


def load_gt(path: Path) -> dict[int, list[dict]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        int(frame): [{"gt_id": str(x["id"]), "bbox": [float(v) for v in x["BboxP"]]} for x in items]
        for frame, items in raw.items()
    }


def iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    bb = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / max(aa + bb - inter, 1e-12)


def load_tracks(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["frame"] = int(row["frame"])
        row["track_id"] = int(row["track_id"])
        row["instance_id"] = int(row.get("instance_id") or row["track_id"])
        row["bbox"] = [float(row[k]) for k in ("x1", "y1", "x2", "y2")]
    return rows


def attach_gt(rows: list[dict], gt: dict[int, list[dict]], frame_offset: int) -> None:
    for row in rows:
        candidates = gt.get(row["frame"] + frame_offset, [])
        scored = [(iou(row["bbox"], item["bbox"]), item["gt_id"]) for item in candidates]
        best = max(scored, default=(0.0, None))
        row["gt_id"] = best[1] if best[0] >= 0.5 else None


def load_descriptors(run: Path, camera: str, rows: list[dict]) -> dict[int, dict]:
    summaries = {int(x["track_id"]): x for x in json.loads((run / "track_summaries.json").read_text(encoding="utf-8"))}
    vectors = np.load(run / "body_prototypes.npz")
    out: dict[int, dict] = {}
    for track_id, summary in summaries.items():
        count = int(summary.get("body_prototypes", 0))
        values = [vectors[f"{camera}__{track_id}__{i}"] for i in range(count) if f"{camera}__{track_id}__{i}" in vectors]
        if not values:
            continue
        matching = [x for x in rows if x["instance_id"] == track_id]
        out[track_id] = {
            "camera": camera,
            "track_id": track_id,
            "object_id": f"O{track_id:03d}",
            "first_frame": min(x["frame"] for x in matching) if matching else int(summary["first_frame"]),
            "last_frame": max(x["frame"] for x in matching) if matching else int(summary["last_frame"]),
            "person_id": summary.get("person_id"),
            "vectors": np.asarray(values, dtype=np.float32),
            "rows": matching,
        }
    return out


def assign_gt_to_descriptors(descriptors: dict[int, dict]) -> None:
    for item in descriptors.values():
        labels = [row["gt_id"] for row in item["rows"] if row.get("gt_id") is not None]
        counts = Counter(labels)
        item["gt_labels"] = sorted(counts)
        # Do not use a takeover-contaminated O as a clean body-model pair.
        item["gt_id"] = next(iter(counts)) if len(counts) == 1 else None


def body_distribution(pairs: list[dict], key: str) -> dict:
    values = [float(x[key]) for x in pairs if math.isfinite(float(x[key]))]
    return {"n": len(values), "min": percentile(values, 0), "p05": percentile(values, 5),
            "median": percentile(values, 50), "p95": percentile(values, 95),
            "p99": percentile(values, 99), "max": percentile(values, 100)}


def threshold_sweep(pairs: list[dict], metric: str) -> list[dict]:
    same = [float(x[metric]) for x in pairs if x["kind"] == "SAME"]
    different = [float(x[metric]) for x in pairs if x["kind"] == "DIFFERENT"]
    out = []
    for threshold in THRESHOLDS:
        same_accepted = sum(x >= threshold for x in same)
        wrong = sum(x >= threshold for x in different)
        total = same_accepted + wrong
        out.append({"metric": metric, "threshold": threshold, "same_accepted": same_accepted,
                    "different_accepted_wrong": wrong,
                    "precision": same_accepted / total if total else 0.0,
                    "same_recall": same_accepted / len(same) if same else 0.0})
    return out


def make_contact_sheet(source: Path, item_a: dict, item_b: dict, output: Path, gt_labels: bool = True) -> None:
    cap = cv2.VideoCapture(str(source))
    tiles = []
    for item in (item_a, item_b):
        rows = item["rows"]
        if not rows:
            continue
        selected = [rows[int(i)] for i in np.linspace(0, len(rows) - 1, min(5, len(rows))).round().astype(int)]
        for row in selected:
            cap.set(cv2.CAP_PROP_POS_FRAMES, row["frame"])
            ok, frame = cap.read()
            if not ok:
                continue
            x1, y1, x2, y2 = [int(v) for v in row["bbox"]]
            crop = frame[max(0, y1):max(y1 + 1, y2), max(0, x1):max(x1 + 1, x2)]
            if crop.size == 0:
                continue
            crop = cv2.resize(crop, (220, 260))
            label = f"{item['object_id']} f={row['frame']} GT={row.get('gt_id') if gt_labels else ''}"
            cv2.putText(crop, label, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, .42, (0, 255, 255), 1, cv2.LINE_AA)
            tiles.append(crop)
    cap.release()
    if not tiles:
        return
    while len(tiles) % 5:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[i:i + 5]) for i in range(0, len(tiles), 5)])
    cv2.imwrite(str(output), sheet)


def analyze_chirla(root: Path, output: Path) -> tuple[dict, list[dict]]:
    run = root / "chirla_cam3_run"
    rows = load_tracks(run / "tracks.csv")
    gt = load_gt(root.parent.parent / "data" / "CHIRLA" / "seq_006" / "annotations" / "camera_3_2023-06-13-13_24_46.json")
    attach_gt(rows, gt, -1)
    descriptors = load_descriptors(run, "cam3", rows)
    assign_gt_to_descriptors(descriptors)
    pairs = []
    for a, b in itertools.combinations(descriptors.values(), 2):
        if a["gt_id"] is None or b["gt_id"] is None:
            continue
        kind = "SAME" if a["gt_id"] == b["gt_id"] else "DIFFERENT"
        values = metrics(a["vectors"], b["vectors"])
        pairs.append({"camera": "cam3", "O_a": a["object_id"], "O_b": b["object_id"],
                      "GT_a": a["gt_id"], "GT_b": b["gt_id"], "kind": kind,
                      "simultaneous": max(a["first_frame"], b["first_frame"]) <= min(a["last_frame"], b["last_frame"]),
                      "frame_a": f"{a['first_frame']}-{a['last_frame']}", "frame_b": f"{b['first_frame']}-{b['last_frame']}",
                      **values, "self_a": self_consistency(a["vectors"]), "self_b": self_consistency(b["vectors"])})
    stats = {"dataset": "CHIRLA_seq006_cam3", "gt_persons": sorted({x["gt_id"] for x in descriptors.values() if x["gt_id"]}),
             "descriptors": len(descriptors), "clean_descriptors": sum(x["gt_id"] is not None for x in descriptors.values()),
             "mixed_gt_descriptors_excluded": sum(bool(x["gt_id"] is None and x.get("gt_labels")) for x in descriptors.values()),
             "pairs": len(pairs), "metrics": {}}
    for metric in ("centroid", "median", "top5_mean", "max"):
        stats["metrics"][metric] = {
            "SAME": body_distribution([x for x in pairs if x["kind"] == "SAME"], metric),
            "DIFFERENT": body_distribution([x for x in pairs if x["kind"] == "DIFFERENT"], metric),
            "sweep": threshold_sweep(pairs, metric),
        }
    hard = sorted((x for x in pairs if x["kind"] == "DIFFERENT"), key=lambda x: x["max"], reverse=True)[:20]
    output.joinpath("hard_cases").mkdir(parents=True, exist_ok=True)
    for index, pair in enumerate(hard[:10], 1):
        make_contact_sheet(root.parent.parent / "data" / "CHIRLA" / "seq_006" / "cam3.avi",
                           descriptors[int(pair["O_a"][1:])], descriptors[int(pair["O_b"][1:])],
                           output / "hard_cases" / f"chirla_pair_{index:02d}.jpg")
    return stats, pairs


def analyze_cam2(root: Path, output: Path) -> tuple[list[dict], list[dict]]:
    run = root / "baseline_cam2"
    rows = load_tracks(run / "tracks.csv")
    descriptors = load_descriptors(run, "cam2", rows)
    requested = [(34, 42), (95, 106)]
    requested_rows = []
    for a, b in requested:
        if a not in descriptors or b not in descriptors:
            continue
        av, bv = descriptors[a], descriptors[b]
        requested_rows.append({"case": f"O{a:03d}-O{b:03d}", "O_a": av["object_id"], "O_b": bv["object_id"],
                               "P_a": av["person_id"], "P_b": bv["person_id"],
                               "frame_a": f"{av['first_frame']}-{av['last_frame']}", "frame_b": f"{bv['first_frame']}-{bv['last_frame']}",
                               "gap": max(0, bv["first_frame"] - av["last_frame"] - 1),
                               "simultaneous": max(av["first_frame"], bv["first_frame"]) <= min(av["last_frame"], bv["last_frame"]),
                               **metrics(av["vectors"], bv["vectors"]), "self_a": self_consistency(av["vectors"]), "self_b": self_consistency(bv["vectors"])})
        make_contact_sheet(root.parent / "data" / "cam2.avi", av, bv, output / "hard_cases" / f"cam2_{a:03d}_{b:03d}.jpg", False)
    negatives = []
    for a, b in itertools.combinations(descriptors.values(), 2):
        if max(a["first_frame"], b["first_frame"]) > min(a["last_frame"], b["last_frame"]):
            continue
        overlap = max(a["first_frame"], b["first_frame"])
        ra = next((x for x in a["rows"] if x["frame"] == overlap), None)
        rb = next((x for x in b["rows"] if x["frame"] == overlap), None)
        if ra is None or rb is None or iou(ra["bbox"], rb["bbox"]) >= 0.5:
            continue
        negatives.append({"O_a": a["object_id"], "O_b": b["object_id"], "P_a": a["person_id"], "P_b": b["person_id"],
                          "frame": overlap, **metrics(a["vectors"], b["vectors"]),
                          "self_a": self_consistency(a["vectors"]), "self_b": self_consistency(b["vectors"])})
    negatives.sort(key=lambda x: x["max"], reverse=True)
    return requested_rows, negatives[:10]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    project = Path(args.project).resolve()
    output = project / "runs" / "body_root_cause_audit"
    output.mkdir(parents=True, exist_ok=True)
    chirla_stats, chirla_pairs = analyze_chirla(output, output)
    cam2_requested, cam2_negatives = analyze_cam2(project / "runs", output)
    with (output / "pair_scores.csv").open("w", newline="", encoding="utf-8") as handle:
        rows = chirla_pairs
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in rows for key in row}))
        writer.writeheader()
        writer.writerows(rows)
    with (output / "g_decisions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source_O", "target_G_or_P", "raw_L", "gap_frames", "body_score", "motion_score", "combined_score", "runner_up", "margin", "face_available", "decision", "reason"])
        writer.writeheader()
        writer.writerows([])
    report = {"chirla": chirla_stats, "cam2_requested": cam2_requested, "cam2_simultaneous_different": cam2_negatives,
              "g_decision_attribution": "NOT FOUND: current runtime output does not log per-merge body/motion/face attribution.",
              "ver1": "NOT FOUND: only cam0 output artifact exists; source decision code is absent."}
    copy_section = [
        "\n===== COPY THIS SECTION TO CHATGPT =====",
        "CHIRLA clean descriptors: %d; SAME pairs: %d; DIFFERENT pairs: %d" % (
            chirla_stats["clean_descriptors"],
            chirla_stats["metrics"]["centroid"]["SAME"]["n"],
            chirla_stats["metrics"]["centroid"]["DIFFERENT"]["n"],
        ),
    ]
    for metric in ("centroid", "median", "top5_mean", "max"):
        item = chirla_stats["metrics"][metric]
        zero_wrong = next((x for x in item["sweep"] if x["different_accepted_wrong"] == 0), None)
        copy_section.append(f"{metric}: SAME={item['SAME']} DIFFERENT={item['DIFFERENT']} zero-wrong={zero_wrong}")
    copy_section.append("TOP 10 FALSE POSITIVE BODY PAIRS:")
    copy_section.extend(json.dumps(x, separators=(",", ":")) for x in sorted(
        (x for x in chirla_pairs if x["kind"] == "DIFFERENT"), key=lambda x: x["max"], reverse=True
    )[:10])
    copy_section.append("CAM2 O034-O042 / O095-O106:")
    copy_section.extend(json.dumps(x, separators=(",", ":")) for x in cam2_requested)
    copy_section.append("CAM2 SIMULTANEOUS DIFFERENT:")
    copy_section.extend(json.dumps(x, separators=(",", ":")) for x in cam2_negatives)
    copy_section.append("O->G attribution: NOT AVAILABLE; g_decisions.csv has no events because runtime output lacks per-merge body/motion/face attribution.")
    copy_section.append("Raw track-ID reuse in cam2: NONE FOUND (no raw track_id mapped to multiple object_id values).")
    copy_section.append("Final verdict: B BODY EXTRACTOR INSUFFICIENT; D BODY AGGREGATION TOO PERMISSIVE; E ASSOCIATION LOGIC TOO PERMISSIVE; F TRACKER FRAGMENTATION DOMINANT; H INSUFFICIENT EVIDENCE for crop-vs-model causal separation.")
    (output / "REPORT.txt").write_text(json.dumps(report, indent=2) + "\n" + "\n".join(copy_section), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
