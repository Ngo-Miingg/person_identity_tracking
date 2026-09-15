# Runtime UI Forensics

**Test job:** `0ffadbe2abc3`  
**Browser:** Chrome Headless via DevTools Protocol  
**Frontend:** `http://127.0.0.1:5173`  
**Backend:** `http://127.0.0.1:8000`  

## Root Cause 1 — Completed Jobs Were Not Replayable

### Evidence

Before the fix, `media_descriptor()` returned:

```text
playback_url: null
warning: MP4 is download-only until a browser-compatible encoder is configured.
```

`LiveMonitorView` rendered an `<img>` snapshot for every non-running job. This made a completed session appear as a live/snapshot monitor with no timeline or seek controls.

### Fix

- Completed jobs now expose `media.playback_url` pointing to that job's own `*_identity.mp4` artifact.
- Completed jobs render a native `<video controls>` element.
- Playback controls include seek, pause/play, fullscreen, and speed selection (`0.5x`, `1x`, `1.5x`, `2x`), defaulting to `1x`.
- Running jobs continue to use the live MJPEG path.
- The viewport label changes to `SESSION REPLAY` for completed jobs.

### Runtime Result

Browser requested:

```text
GET /api/jobs/0ffadbe2abc3/artifacts/c7b603ace977_identity.mp4
Response: 206 Partial Content
HTML element: VIDEO
controls: true
playbackRate: 1
```

The server's `FileResponse` supports browser range requests. Timeline seeking is therefore available through native HTML5 video.

## Root Cause 2 — Selected Job Association

### Evidence

Browser navigation used the same job ID across all views:

```text
#view=live&job=0ffadbe2abc3
#view=identities&job=0ffadbe2abc3
#view=pipeline&job=0ffadbe2abc3
```

All captured API/media requests used `0ffadbe2abc3`, including:

```text
/api/jobs/0ffadbe2abc3/summary
/api/jobs/0ffadbe2abc3/telemetry
/api/jobs/0ffadbe2abc3/tracks
/api/jobs/0ffadbe2abc3/identities
/api/jobs/0ffadbe2abc3/details
/api/jobs/0ffadbe2abc3/artifacts/c7b603ace977_identity.mp4
```

### Fix

`LiveMonitorView` now accepts a WebSocket snapshot only when its ID matches the selected job:

```text
wsJob?.id === selectedJob?.id ? wsJob : selectedJob
```

Changing jobs also clears old summary, tracks, telemetry, media error state, and playback speed before loading the new job.

### Runtime Result

No cross-job media request was observed. The replay source contained the selected job ID and its matching artifact filename.

## Root Cause 3 — Identity Hub Empty State

### Evidence

For `0ffadbe2abc3`, the artifact and API both contained identity profiles:

```text
GET /api/jobs/0ffadbe2abc3/identities -> 200
Rendered profiles: P001, P002, P003, P004
Identity crop requests: 200
```

The browser rendered the profiles and face/body samples. For jobs with no profiles, the old text implied only that verification was missing and did not distinguish zero profiles from zero detections.

### Fix

The empty state now explicitly says:

```text
No Persistent Identity Profiles
This completed session produced no persistent face-anchored profiles.
This is distinct from having no detections or tracklets.
```

It also shows job status and track-row count.

## Root Cause 4 — Tracklet Ledger Contradiction

### Evidence Before Fix

Job `843a6cb26e9b` returned:

```text
SQLite tracklets: 13
details.tracks: 0
```

The ledger used `details.tracks`, which was loaded only from `track_summaries.json`. The job failed during final reconciliation, so that artifact was absent even though SQLite already contained 13 tracklets.

### Fix

`GET /api/jobs/{id}/details` now queries SQLite tracklets directly and returns `tracklets` rows with:

- tracklet ID
- camera
- local track ID
- frame span
- latest assignment state/reason
- face/body observation counts

The pipeline UI uses the finalized `tracks` summary when available and falls back to SQLite-backed `tracklets` rows otherwise. The count is sourced from the same database.

### Runtime Result on Completed Job

```text
SQLite tracklets: 20
Ledger rendered: 20 tracklets recorded
Detections: 2467
Observations: 1282
Assignments: 26
```

## Root Cause 5 — Fusion Decisions and Identity Events

### SQLite Evidence for `0ffadbe2abc3`

```text
PRAGMA integrity_check: ok
tracklets:          20
detections:         2467
observations:       1282
assignments:        26
fusion_decisions:   20
identity_events:    0
```

### Interpretation

- `fusion_decisions = 20` is active persistence, not a frontend fabrication. `infer_engine.py` calls `identity_db.add_fusion_decision()` during final track reconciliation.
- `identity_events` SQLite table is currently unused by the pipeline. The event artifact `identity_events.json` contains 20 events, and `/details` reads that JSON for the ticker. The UI now labels the two values separately as `SQLite Identity Events` and `Artifact Identity Events`.
- For failed job `843a6cb26e9b`, `fusion_decisions = 0` is explained by the real traceback: reconciliation crashed before the final fusion loop.

### Persistence Bug Found and Prevented

The failed job crashed at:

```text
PersonMemory.reconcile_track_faces
KeyError: 1
```

The newly added mid-run profile eviction removed a profile that final reconciliation still referenced. The mid-run eviction call was removed so final reconciliation cannot operate on deleted profiles.

## Video FPS Forensics

Measured with OpenCV on job `0ffadbe2abc3`:

| Artifact | FPS | Frames | Duration |
|---|---:|---:|---:|
| Source `c7b603ace977.mp4` | 29.907 | 10,312 | 344.800 s |
| Identity MP4 | 29.907 | 10,312 | 344.802 s |
| Local Identity MP4 | 29.907 | 10,312 | 344.802 s |

The output writer is not producing half-speed video for this completed job. The observed slow experience came from the UI using snapshot/live semantics instead of a seekable completed MP4 player.

## Browser E2E Result

```text
Selected job isolation:       PASS
Completed MP4 replay:          PASS
Native controls/timeline:      PASS
HTTP Range response:           PASS (206)
Identity API/profile rendering: PASS
Pipeline ledger consistency:   PASS (20 DB rows / 20 displayed)
Fusion decision persistence:   PASS for completed job (20 rows)
Cross-job media observed:      NO
Browser runtime exceptions:    0
Network loading failures:      0 except normal media abort during source reload
```

## Remaining Issues

- SQLite `identity_events` remains an unused table while the authoritative event artifact is `identity_events.json`. The UI now exposes this distinction rather than conflating the counts.
- The older failed job `843a6cb26e9b` remains a historical partial artifact and was not modified or deleted.
- Crowd, low-light, re-entry, and crossing identity accuracy remain outside this runtime UX fix.
