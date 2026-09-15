import argparse
import json
from pathlib import Path

def convert_chirla_to_e4(
    chirla_json_path: str,
    output_e4_path: str,
    dataset_name: str = "CHIRLA_seq_006_cam3.avi",
    fps: float = 30.0,
    max_frames: int = 500,
) -> None:
    src_path = Path(chirla_json_path)
    out_path = Path(output_e4_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with src_path.open("r", encoding="utf-8") as f:
        chirla = json.load(f)

    e4_frames = []
    # Keys in CHIRLA are 1-based frame numbers as strings: "1", "2", ...
    sorted_frames = sorted((int(k), k) for k in chirla.keys())
    
    gt_person_mapping = {}

    for frame_idx, key in sorted_frames[:max_frames]:
        persons = []
        raw_items = chirla.get(key, [])
        for item in raw_items:
            raw_id = item["id"]
            gt_id = f"GT{raw_id:03d}"
            # BboxP in CHIRLA: [x1, y1, x2, y2]
            bbox = [float(c) for c in item["BboxP"]]
            persons.append({
                "gt_id": gt_id,
                "employee_id": None,  # Open-set anonymous surveillance
                "bbox": bbox,
                "visible": True,
                "face_visible": False,  # Anonymous body tracking
                "occluded": False,
            })
            gt_person_mapping[gt_id] = raw_id

        e4_frames.append({
            "frame": frame_idx - 1,  # 0-indexed frame for pipeline comparison
            "persons": persons,
        })

    e4_payload = {
        "dataset": dataset_name,
        "fps": fps,
        "frame_count": len(e4_frames),
        "total_unique_gt_persons": len(gt_person_mapping),
        "annotations": e4_frames,
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(e4_payload, f, indent=2)

    print(f"[E4-CONVERTER] Wrote {len(e4_frames)} frames with {len(gt_person_mapping)} GT persons to {out_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chirla", default=r"data\CHIRLA\seq_006\annotations\camera_3_2023-06-13-13_24_46.json")
    parser.add_argument("--out", default=r"evaluation\annotations\chirla_seq006_cam3_ground_truth.json")
    parser.add_argument("--max-frames", type=int, default=500)
    args = parser.parse_args()
    convert_chirla_to_e4(args.chirla, args.out, max_frames=args.max_frames)
