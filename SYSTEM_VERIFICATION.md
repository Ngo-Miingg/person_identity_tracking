# System Verification Report — Grounded Verification

**Verification Date:** 2026-09-11  
**Target Project:** Person Identity Tracking (`v2.1.0-face-anchor-authority`)  
**Environment:** Windows x64 · NVIDIA RTX 3050 6GB Laptop GPU · Python 3.11 (`.venv`) · Node v22  

---

## 1. Regression & Hardening Test Matrix

| Test Case | Feature Under Test | Expected Behavior | Observed Runtime Behavior | Level | Verdict |
|---|---|---|---|:---:|:---:|
| **AUTH-01** | HttpOnly Cookie Auth | Browser session verified without plain text token in URL | Verified via `verify_token(cookie_token=...)` | **E3** | **PASS** |
| **AUTH-02** | Short-Lived Access Ticket | Ticket valid before expiration (60s), rejected after | Tested with TTL 0.5s: pass at 0.1s, fail at 0.6s | **E3** | **PASS** |
| **AUTH-03** | Frontend Secret Elimination | No master API key bundled in client static Javascript | `Select-String` found 0 matches in `dist/assets/*.js` | **E3** | **PASS** |
| **LOCK-01** | Cross-Process Execution Lock | File-backed atomic mutex prevents multi-worker collision | `CrossProcessExecutionLock` acquires and releases cleanly | **E2/E3** | **PASS** |
| **DISK-01** | Disk Free Space Safety Guard | Operation rejected when free disk $< 2.0\text{ GB}$ | Raises HTTP 507 with descriptive warning | **E2/E3** | **PASS** |
| **DISK-02** | Automatic Storage Retention | Oldest terminal jobs pruned when storage $> 50\text{ GB}$ | Terminal jobs filtered and safely unlinked; active jobs protected | **E2/E3** | **PASS** |
| **PID-01** | PID Reuse Guard (Mismatched Time) | Mismatched `create_time` aborts kill | Logged `[PID-REUSE-GUARD] Stale PID detected... Skipping kill.` | **E2/E3** | **PASS** |
| **MEM-01** | PersonMemory RAM Eviction | Inactive anonymous profiles evicted after TTL | 10 profiles created, 5 active retained, 5 archived to cold store | **E2/E3** | **PASS** |
| **E4-01** | Ground-Truth IoU Matching | Evaluator matches predictions to ground truth via IoU $\ge 0.5$ | 23 frames matched on `cam0_clip_ground_truth.json` | **E4** | **PASS** |
| **E4-02** | FPIR Evaluation Benchmark | Unknown person observations never classified as employee | 0 false promotions across 23 observations (FPIR = 0.00%) | **E4** | **PASS** |

---

## 2. Automated Test Suite Execution Summary

```powershell
& .venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

* **Adversarial Invariant Tests (`test_adversarial_scenarios.py`):** 6/6 PASSED
* **Face Authority Policy Tests (`test_face_authority.py`):** 6/6 PASSED
* **Hardening & Remediations (`test_hardening_remediation.py`):** 6/6 PASSED
* **Regression Suite (`test_all_regressions_suite.py`):** 2/2 Offline tests PASSED (5 live network tests skipped when server offline)
* **Total Executed Tests:** 20 PASSED, 0 FAILED

---

## 3. Operational Deployment Status

| Environment Target | Readiness | Technical Pre-requisites Remaining |
|---|:---:|---|
| **Local Operator Workstation** | **YES** | Ready for single-operator execution via `start_console.ps1`. |
| **Trusted Private LAN** | **YES** | Only with controlled network access; tokens are removed from URLs and bundle. |
| **Untrusted / Shared LAN** | **NO** | Requires HTTPS/WSS and appropriate operator authorization. |
| **Internet Production** | **NO** | Requires Production TLS reverse proxy (Nginx/Caddy) and multi-user RBAC. |
| **Biometric Security / Access Control** | **NO** | Lacks liveness / presentation attack detection (PAD). |
| **Identity Analytics Pilot** | **YES** | Limited to the current benchmarked operational scope; not accuracy-certified. |
