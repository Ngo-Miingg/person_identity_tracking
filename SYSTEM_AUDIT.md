# System Audit — Remediated & Hardened

## 1. Executive Summary

```text
Historical Software Bugs (BUG-001..BUG-011): 11 FIXED + VERIFIED
Architecture Findings:                          0 critical blockers in current local single-operator analytics scope

Build Correctness:                    PASS
Runtime Integration:                  PASS
End-to-End Pipeline Execution:        PASS (Execution verified on short_test_clip.avi)
AI Policy Invariants:                 PASS (Unit test verified)
Real-World Identity Accuracy:         LIMITED E4 VERIFIED (N=1 unknown person / 23 matched observations)

Security for Local Single-Operator:   YES (HttpOnly cookie / Bearer auth, no secrets in JS)
Security for Trusted Private LAN:     YES (Controlled network access required)
Security for Untrusted Shared LAN:    NO (Requires HTTPS/WSS and stronger operator authorization)
Security for Internet Production:     NO (Requires TLS reverse proxy + RBAC if multi-user)
Production Ready:                     NO (Pending TLS gateway, hardened sessions, and RBAC if multi-user)
Internal Demo Ready:                  YES
Internal Handoff Ready:               YES
```

---

## 2. Architecture Remediations Verified (FINDING-01..FINDING-07)

### FINDING-01: Master Token Exposure Remediated
- **Resolution:**
  - Removed `VITE_API_KEY` from frontend code and bundle. Client-side bundle `dist/assets/*.js` contains zero plain-text master tokens.
  - Media URLs (`<img>`), WebSocket endpoints, and download links no longer expose `?token=PIT_API_KEY`.
  - Added `/api/auth/session` issuing HttpOnly cookies with `SameSite=Lax`.
  - Added short-lived access tickets (`/api/auth/ticket`, TTL 60s) for non-cookie media/WebSocket requests.
- **Status:** **FIXED + VERIFIED (E3)**

### FINDING-02: Multi-Worker GPU Lock Safety Remediated
- **Resolution:**
  - Implemented `CrossProcessExecutionLock` using OS-level file locking (`msvcrt.locking` on Windows, `fcntl.flock` on POSIX) coupled with `threading.Lock`.
  - Added startup assertion `MAX_BACKEND_WORKERS=1` enforcing that backend runs as a single worker process by design.
- **Status:** **FIXED + VERIFIED (E2/E3)**

### FINDING-03: Storage Quota & Disk Safety Remediated
- **Resolution:**
  - Implemented `_ensure_disk_safety(required_bytes)` enforcing a strict minimum threshold (`PIT_MIN_FREE_DISK_GB=2.0`). Uploads and job submissions are deterministically rejected with HTTP 507 if disk space is insufficient.
  - Implemented automated retention pruning `auto_prune_if_exceeded()` that cleans up expired or oversized terminal jobs on job submission without deleting active/running jobs.
- **Status:** **FIXED + VERIFIED (E2/E3)**

### FINDING-04: PID Reuse Protection Remediated
- **Resolution:**
  - Worker spawn now captures and persists `process_create_time` via `psutil`.
  - Reconciled kill logic `_kill_process_tree` validates PID, creation timestamp ($\pm 2.0s$), and command line signature before issuing termination.
  - Stale PID records from rebooted systems are safely skipped without killing unrelated Python processes.
- **Status:** **FIXED + VERIFIED (E2/E3)**

### FINDING-05: Missing E4 Ground Truth Remediated
- **Resolution:**
  - Built evaluation framework in `evaluation/` with standardized ground-truth schema, annotation generator, and `evaluate_identity.py`.
  - Created the benchmark annotation artifact on `cam0.avi` (`cam0_clip_ground_truth.json`); it contains one unknown-person trajectory and no employee labels.
  - Executed reproducible evaluation run generating `evaluation/reports/cam0_benchmark_report.json` and documented in `E4_IDENTITY_BENCHMARK.md`.
- **Status:** **BENCHMARK PIPELINE VERIFIED (E4)**

### FINDING-06: PersonMemory Profile Eviction Remediated
- **Resolution:**
  - Added LRU/TTL lifecycle manager `evict_inactive_profiles(current_frame)` in `PersonMemory`.
  - Stale anonymous profiles with no active tracks are evicted from active RAM search set after `anonymous_profile_ttl_frames` (default 1500 frames), capping memory consumption to `max_active_anonymous_profiles` (default 200).
  - Historical records remain fully archived in SQLite and `archived_profiles` for forensic export.
- **Status:** **FIXED + VERIFIED (E2/E3)**

### FINDING-07: Liveness / Anti-Spoofing Scope Documented
- **Specification:**
  - The system is architected as an **Employee Monitoring and Video Analytics** solution.
  - It does **NOT** include Presentation Attack Detection (PAD / Liveness).
  - Scope is formally restricted: **CANNOT** be deployed as an unattended biometric access-control system.
- **Status:** **DOCUMENTED & BOUNDED (E1)**
