# Identity Validation Report — E4 Validated & Hardened

**Audit Date:** 2026-09-11  
**Project:** Person Identity Tracking (`v2.1.0-face-anchor-authority`)  
**Scope:** AI Model Cascade (`YOLO11s` $\rightarrow$ `BoT-SORT` $\rightarrow$ `SCRFD 10G` $\rightarrow$ `AdaFace IR50` $\rightarrow$ `OSNet x1.0` $\rightarrow$ `Evidence Fusion`)  

---

## 1. Ground Truth Benchmark Results (Level E4)

Empirical evaluation executed on the available benchmark annotation artifact `evaluation/annotations/cam0_clip_ground_truth.json`:

```json
{
  "dataset": "cam0_clip150_200.avi",
  "total_gt_frames": 34,
  "unique_gt_persons": 1,
  "unique_gt_employees": 0,
  "matched_detections": 23,
  "unmatched_gt_detections": 11,
  "tracker_fragmentation_switches": 0,
  "persistent_identity_switches": 0,
  "false_merges": 0,
  "false_splits": 0,
  "fpir": {
    "rate": 0.0,
    "false_promotions": 0,
    "total_unknown_observations": 23
  }
}
```

### Empirical Metric Summary
* **Evaluated Dataset:** `cam0_clip150_200.avi` (50 frames, 34 active person frames)
* **Evaluable Observations:** 23 IoU-matched detection frames
* **Evaluable Persons:** 1 GT Unknown Visitor (`GT001`)
* **Tracker Fragmentation Switches:** **0** (Track ID 4 maintained)
* **Persistent Identity Switches:** **0**
* **False Merges:** **NOT EVALUABLE** — requires at least 2 distinct ground-truth identities.
* **False Splits:** **0**
* **False Positive Identification Rate (FPIR):** **0 / 23 = 0.00%** (Observed on N=1 subject)

> **Notice on Scope:** This empirical evaluation validates that the pipeline tracks an unknown visitor without false employee promotion. It does **NOT** certify enterprise-wide recognition accuracy across multi-subject galleries due to the current sample size ($N=1$).

---

## 2. Policy Invariants & Algorithmic Controls (Level E2)

* **Face Authority Invariant:** Body ReID alone cannot confirm an employee (`test_e1` PASS).
* **Face Overrides Body Conflict:** When face matches Candidate A and body matches Candidate B, Face authority decides Candidate A (`test_e2` PASS).
* **Crossing Ambiguity Freeze:** $IoU \ge 0.50$ sets `has_ambiguity = True` and freezes prototype learning (`test_d4`, `test_f1` PASS).
* **Memory Reservoir Limits:** Inactive profiles are evicted via LRU/TTL logic; maximum views per profile capped at 20 (`test_f4`, `test_person_memory_eviction_bounds` PASS).

---

## 3. Scope & Operational Limitations

* **Application Domain:** Workplace video analytics, presence tracking, and visitor flow monitoring.
* **Liveness / Anti-Spoofing:** **NONE** (System does not contain Presentation Attack Detection).
* **Security Certification:** **NOT CERTIFIED** for unattended biometric access control or high-security physical authorization.

> **Annotation provenance:** This artifact has one unknown-person trajectory and no employee labels. Independent annotation review remains required before treating it as a formal population-level acceptance dataset.

---

## 4. Current Evidence Classification

```text
Real-World Identity Validation:   LIMITED E4 VERIFIED
                                  (N=1 unknown person / 23 matched observations)
General Real-World Accuracy:      NOT YET VERIFIED
Real-World Re-entry Accuracy:     NOT VERIFIED (E2 policy evidence only)
Real-World Crossing Preservation: NOT VERIFIED (E2 geometry/freeze evidence only)
Crowd Identity Robustness:        NOT VERIFIED
Low-Light Identity Robustness:    NOT VERIFIED
```
