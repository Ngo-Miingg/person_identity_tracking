# Final Evidence Matrix — Complete Remediation & Verification

**System:** Person Identity Tracking (`v2.1.0-face-anchor-authority`)  
**Audit Purpose:** Comprehensive mapping of architectural findings, evidence levels, and verified claims.  

---

## 1. Finding Remediation Status

| Finding ID | Title | Historical Severity | Remediation Method | Evidence Level | Status |
|---|---|:---:|---|:---:|:---:|
| **FINDING-01** | Master API Key Exposure | HIGH | Removed `VITE_API_KEY` from bundle; eliminated tokens in URLs; added HttpOnly cookie session & short-lived tickets. | **E3** | **FIXED + VERIFIED** |
| **FINDING-02** | Multi-Worker Lock Safety | HIGH | Implemented OS file-backed `CrossProcessExecutionLock` + startup assertion `MAX_BACKEND_WORKERS=1`. | **E2/E3** | **FIXED + VERIFIED** |
| **FINDING-03** | Storage Quota & Disk Safety | MEDIUM | Added `_ensure_disk_safety` (2GB min free disk check) + automatic retention prune before new jobs. | **E2/E3** | **FIXED + VERIFIED** |
| **FINDING-04** | PID Reuse Risk | MEDIUM | Worker persists `process_create_time`; kill logic verifies PID + creation timestamp before termination. | **E2/E3** | **FIXED + VERIFIED** |
| **FINDING-05** | Missing E4 Ground Truth | HIGH | Established `evaluation/` pipeline, annotated `cam0_clip_ground_truth.json`, executed `evaluate_identity.py`. | **E4** | **BENCHMARK ESTABLISHED** |
| **FINDING-06** | PersonMemory RAM Growth | MEDIUM | Implemented `evict_inactive_profiles` with TTL and profile capacity bounds; verified via unit test. | **E2/E3** | **FIXED + VERIFIED** |
| **FINDING-07** | Liveness / Anti-Spoofing Scope | MEDIUM | Formally bounded scope as Video Analytics only; explicitly documented absence of PAD / liveness. | **E1** | **DOCUMENTED & BOUNDED** |

---

## 2. Complete Evidence Matrix

| Claim | Evidence Level | Verification Method | Sample Size | Observed Result | Allowed Claim |
|---|:---:|---|:---:|---|---|
| **Frontend Bundle Secret-Free** | **E3** | String search on `frontend/dist/` | 34 modules | Zero plain text master tokens found | **Secret-Free Client Bundle (E3)** |
| **HttpOnly Cookie Auth** | **E3** | Python unit test / API request | 2 assertions | Cookie verifies operator access | **HttpOnly Session Auth Pass (E3)** |
| **Short-Lived Ticket Expiry** | **E3** | TTL test (0.5s ticket) | 2 ticket checks | Valid at 0.1s, rejected at 0.6s | **Short-Lived Ticket Verified (E3)** |
| **Cross-Process Execution Lock** | **E2/E3** | File lock acquisition test | 1 lock file | File mutex acquired and released cleanly | **Cross-Process Lock Verified (E2/E3)** |
| **Disk Space Safety Enforcement** | **E2/E3** | Requested 1000 TB check | 1 check | Raises HTTP 507 Insufficient Storage | **Disk Safety Check Pass (E2/E3)** |
| **Automatic Retention Pruning** | **E2/E3** | Prune simulation on candidate jobs | 1 run | Old terminal jobs pruned safely | **Auto Retention Verified (E2/E3)** |
| **PID Reuse Guard** | **E2/E3** | Kill test with mismatched timestamp | 1 test PID | Process kill skipped safely | **PID Reuse Guard Verified (E2/E3)** |
| **Profile Memory Eviction** | **E2/E3** | Eviction test with 10 profiles | 10 profiles | Evicted 5 stale profiles after TTL | **Profile Eviction Verified (E2/E3)** |
| **Face Authority Inviolability** | **E2** | Unit test `test_e1` | 1 test fixture | Body alone produces PROVISIONAL | **Face Authority Invariant (E2)** |
| **Empirical FPIR (Unknown $\rightarrow$ EMP)** | **E4** | `evaluation/evaluate_identity.py` | 23 observations | 0 false promotions (FPIR = 0.00%) | **FPIR = 0/23 on N=1 Benchmark (E4)** |
| **Empirical Persistent ID Switches** | **E4** | Ground-truth trajectory evaluation | 1 GT track | 0 switches across 23 frames | **0 Switches on N=1 Benchmark (E4)** |
| **Empirical False Merges** | **E4** | Multi-GT collision check | 1 GT track | Not evaluable | **NOT EVALUABLE; requires >=2 GT identities** |
| **Empirical False Splits** | **E4** | Multi-PID fragmentation check | 1 GT track | 0 false splits | **0 Splits on N=1 Benchmark (E4)** |
| **Anti-Spoofing / Liveness** | **E1** | Architectural inspection | SCRFD + AdaFace | No PAD classifier present | **NO LIVENESS (Vulnerable to print/screen)** |
| **Internet Production Readiness** | **E1** | Infrastructure inspection | Gateway/Network | Plaintext HTTP/WS, no RBAC | **NOT READY FOR INTERNET PRODUCTION** |
