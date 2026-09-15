# E4 Identity Benchmark Report — Ground-Truth Empirical Evaluation

**Evaluation Date:** 2026-09-11  
**System:** Person Identity Tracking — `v2.1.0-face-anchor-authority`  
**Evaluation Standard:** Level E4 Ground-Truth Empirical Validation (No synthetic embeddings, strictly human/labeled frame comparison).  
**Evaluator Script:** `evaluation/evaluate_identity.py` (IoU threshold: 0.50)  

---

## 1. Ground Truth Benchmark Datasets

| Dataset Key | File Path | Total Labeled Frames | GT Persons | GT Enrolled Employees | Scenario Type | Source |
|---|---|:---:|:---:|:---:|---|---|
| **E4-CAM0-BENCH** | `evaluation/annotations/cam0_clip_ground_truth.json` | 34 active frames (50 total) | 1 (`GT001`) | 0 (Open-set unknown visitor) | Real-world continuous walk across room | Verified human annotation on `cam0.avi` (frames 150..200) |
| **E4-CHIRLA-BENCH** | `evaluation/annotations/chirla_seq006_cam3_ground_truth.json` | 300 frames | 2 (`GT003`, `GT009`) | 0 (Open-set pedestrian surveillance) | Real multi-person pedestrian tracking | CHIRLA sequence 006 multi-camera ground truth |

---

## 2. Empirical Benchmark Evaluation Results

### Benchmark 1: `E4-CAM0-BENCH` (Continuous Indoor Surveillance Clip)
Command executed:
```powershell
& .venv\Scripts\python.exe evaluation/evaluate_identity.py `
  --gt evaluation/annotations/cam0_clip_ground_truth.json `
  --tracks runs/e4_benchmark_run/tracks.csv `
  --out evaluation/reports/cam0_benchmark_report.json
```

| Metric | Ground Truth Value | Model Prediction | Result / Rate | Evidence Level |
|---|:---:|:---:|:---:|:---:|
| **Matched Detection Trajectories** | 34 GT observations | 23 IoU-matched | 67.6% Recall | **E4** |
| **Tracker Fragmentation Switches** | 0 switches | 0 switches (Track ID 4 maintained) | **0 switches** | **E4** |
| **Persistent Identity Switches** | 0 switches | 0 switches | **0 switches** | **E4** |
| **False Merges (Identity Collisions)** | 1 GT person | N/A | **NOT EVALUABLE** | **E4** |
| **False Splits (Identity Fragmentations)** | 0 | 0 | **0 splits** | **E4** |
| **False Positive Identification Rate (FPIR)** | 23 unknown observations | 0 false employee promotions | **0 / 23 = 0.00%** | **E4** |
| **Employee False Negative Rate (FNIR)** | 0 employee observations | N/A | **N/A (No GT employee)** | **E4** |

---

## 3. Strict Scientific Interpretation of Empirical Results

1. **Sample Size Scope (N=1 GT Person):**
   - The observed **0.00% FPIR** on `E4-CAM0-BENCH` is mathematically grounded on **23 evaluable unknown observations of 1 individual**.
   - It **CANNOT** be certified as global 0.00% FPIR for enterprise-wide surveillance without evaluation on a multi-subject benchmark (e.g. 1,000+ distinct identities).
2. **Tracker Continuity (BoT-SORT):**
   - Track ID 4 was maintained across all 23 matched frames without fragmentation.
3. **Face Authority Policy Hold:**
   - Because no face was enrolled in `gallery/` for this test run, zero false promotions to employee occurred.
4. **Held-out Generalization Notice:**
   - There is currently **NO HELD-OUT DATASET** for employee gallery recognition in this repository. All empirical tests evaluate open-set anonymous trajectory tracking.

---

## 4. Benchmark Summary & Allowed Conclusions

```text
================================================================================
E4 BENCHMARK EMPIRICAL SUMMARY
================================================================================

Empirical Ground Truth Evaluated:     YES (E4-CAM0-BENCH, 50 frames)
Evaluated Observations:               23 matched person frames
Evaluated Persons:                    1 GT Unknown individual
Tracker Fragmentation Switches:       0
Persistent Identity Switches:         0
False Merges:                         NOT EVALUABLE (requires >=2 GT identities)
False Splits:                         0
FPIR (Unknown -> Employee):           0 / 23 (0.00% on N=1 subject)

Empirical Status:                     EMPIRICALLY TESTED ON N=1 BENCHMARK
Certified Production Accuracy:        NO (Sample size N=1 insufficient for enterprise SLA)
================================================================================
```
