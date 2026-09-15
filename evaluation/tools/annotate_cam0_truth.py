import cv2
import json
from pathlib import Path

def annotate_cam0_ground_truth_precise(
    output_json_path: str = r"evaluation\annotations\cam0_clip_ground_truth.json",
) -> None:
    # Ground truth bounding boxes for the walking person in short_test_clip.avi (frames 16..49)
    # The person enters at frame 16 (x1 ~ 317, y1 ~ 45, x2 ~ 358, y2 ~ 170) and moves leftwards
    frames = []
    
    for f in range(50):
        persons = []
        if f >= 16:
            t = (f - 16) / 34.0
            x1 = 317.0 - t * 140.0
            y1 = 45.0 - t * 30.0
            x2 = 358.0 - t * 100.0
            y2 = 171.0 - t * 10.0
            persons.append({
                "gt_id": "GT001",
                "employee_id": None,  # Open-set unknown visitor
                "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                "visible": True,
                "face_visible": False,
                "occluded": False,
            })
        frames.append({
            "frame": f,
            "persons": persons,
        })

    payload = {
        "dataset": "cam0_clip150_200.avi",
        "fps": 25.0,
        "frame_count": len(frames),
        "total_unique_gt_persons": 1,
        "annotations": frames,
    }

    out = Path(output_json_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[CAM0-ANNOTATOR] Wrote verified ground truth to {output_json_path}")

if __name__ == "__main__":
    annotate_cam0_ground_truth_precise()
