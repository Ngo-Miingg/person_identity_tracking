from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Person Identity Tracking - Production Inference CLI (v1.0)"
    )
    parser.add_argument("--source", required=True, help="Path to video file, camera index, or RTSP URL")
    parser.add_argument("--output", default="runs/latest", help="Output directory")
    parser.add_argument("--device", default="0", help="GPU device index or 'cpu'")
    parser.add_argument("--gallery", default=None, help="Optional employee photo gallery directory")
    parser.add_argument("--tracker", default=str(PROJECT_ROOT / "tracker_botsort_reid.yaml"), help="Tracker config")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Call main pipeline via subprocess with current python executable
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "infer.py"),
        "--sources", str(args.source),
        "--output", str(out_dir),
        "--device", str(args.device),
        "--tracker", str(args.tracker),
    ]
    if args.gallery:
        cmd.extend(["--gallery", str(args.gallery)])

    print("=" * 76)
    print(" PERSON IDENTITY TRACKING - PRODUCTION RUNNER (v1.0)")
    print("=" * 76)
    print(f"Source: {args.source}")
    print(f"Output: {out_dir}")
    print(f"Device: {args.device}")
    print("-" * 76)

    ret = subprocess.run(cmd)
    if ret.returncode != 0:
        print(f"[ERROR] Inference engine exited with return code {ret.returncode}")
        sys.exit(ret.returncode)

    # 2. Consolidate and guarantee the 4 standard production artifacts:
    #   1. result.mp4
    #   2. tracks.csv
    #   3. identities.csv
    #   4. events.jsonl

    # a. Standardize result.mp4
    mp4_candidates = list(out_dir.glob("*_identity.mp4"))
    if mp4_candidates:
        target_mp4 = out_dir / "result.mp4"
        # If result.mp4 doesn't exist, copy or rename the best candidate
        chosen = [p for p in mp4_candidates if not p.name.endswith("_local_identity.mp4")][0] if any(not p.name.endswith("_local_identity.mp4") for p in mp4_candidates) else mp4_candidates[0]
        if chosen != target_mp4:
            shutil.copy2(chosen, target_mp4)

    # b. Standardize identities.csv from person_memory.json or track_summaries.json
    memory_json = out_dir / "person_memory.json"
    identities_csv = out_dir / "identities.csv"
    if memory_json.is_file():
        try:
            with memory_json.open("r", encoding="utf-8") as f:
                data = json.load(f)
            profiles = data.get("profiles", [])
            with identities_csv.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "person_id", "global_id", "employee_id", "maturity", "confidence",
                    "face_anchor_count", "face_observations", "body_observations", "reacquire_count"
                ])
                for p in profiles:
                    pid = p.get("person_id")
                    pid_int = int(pid.replace("P", "")) if isinstance(pid, str) and pid.startswith("P") else pid
                    writer.writerow([
                        f"P{pid_int:03d}" if pid_int is not None else "",
                        f"G{pid_int:03d}" if pid_int is not None else "",
                        p.get("employee_id") or "UNKNOWN",
                        p.get("maturity", ""),
                        f"{float(p.get('confidence', 0.0)):.4f}",
                        p.get("face_anchor_count", 0),
                        p.get("face_observations", 0),
                        p.get("body_observations", 0),
                        p.get("reacquire_count", 0),
                    ])
        except Exception as err:
            print(f"[WARN] Could not build identities.csv: {err}")

    # c. Standardize events.jsonl
    live_events = out_dir / "live" / "biometric_events.jsonl"
    events_jsonl = out_dir / "events.jsonl"
    if live_events.is_file():
        shutil.copy2(live_events, events_jsonl)
    elif not events_jsonl.is_file():
        events_json = out_dir / "identity_events.json"
        if events_json.is_file():
            try:
                with events_json.open("r", encoding="utf-8") as f:
                    ev_list = json.load(f)
                with events_jsonl.open("w", encoding="utf-8") as f:
                    for ev in ev_list:
                        f.write(json.dumps(ev) + "\n")
            except Exception:
                pass

    # d. Export the O -> G continuity mapping as a stable handoff artifact.
    tracks_csv = out_dir / "tracks.csv"
    global_ids_json = out_dir / "global_ids.json"
    if tracks_csv.is_file():
        try:
            groups = {}
            with tracks_csv.open("r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    object_id = row.get("object_id") or ""
                    global_id = row.get("global_id") or row.get("person_id") or ""
                    if not object_id or not global_id or global_id in {"UNKNOWN", "P:---"}:
                        continue
                    groups.setdefault(global_id, set()).add(object_id)
            payload = {
                "global_ids": [
                    {"global_id": gid, "objects": sorted(objects)}
                    for gid, objects in sorted(groups.items())
                ]
            }
            global_ids_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as err:
            print(f"[WARN] Could not build global_ids.json: {err}")

    print("\n" + "=" * 76)
    print(" PRODUCTION ARTIFACTS READY:")
    print("=" * 76)
    standard_files = ["result.mp4", "tracks.csv", "global_ids.json", "identities.csv", "events.jsonl"]
    for sf in standard_files:
        p = out_dir / sf
        if p.is_file():
            print(f"  [OK] {sf:<16} ({p.stat().st_size:,} bytes)")
        else:
            print(f"  [--] {sf:<16} (not created)")
    print("=" * 76)


if __name__ == "__main__":
    main()
