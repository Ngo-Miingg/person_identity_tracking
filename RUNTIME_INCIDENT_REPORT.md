# Runtime Incident Report

## Symptom

The browser rendered `API: ONLINE`, but `Source Fleet` showed `Failed to fetch`, the source list was empty, the launch modal had no input sources, and the session selector showed `No sessions available`.

## Reproduction

1. Started a clean backend on `127.0.0.1:8000` and Vite frontend on `127.0.0.1:5173`.
2. Opened the application in real headless Chrome through the Chrome DevTools Protocol.
3. Captured console, Network, CORS, response and backend log events.
4. Before remediation, browser requests to `/api/jobs`, `/api/sources`, `/api/cameras`, and `/api/storage` failed in the browser despite the backend being reachable.

## Browser Evidence

Before fix:

```text
Network.loadingFailed
errorText: net::ERR_FAILED
corsErrorStatus: MissingAllowOriginHeader
Request: GET http://127.0.0.1:8000/api/sources
Request cookies: none
```

The public `/api/health` request returned `200`, which explains why the header incorrectly looked healthy.

After fix:

```text
Session bootstrap: POST /api/auth/session -> 200
GET /api/jobs -> 200
GET /api/sources -> 200
GET /api/cameras -> 200
GET /api/storage -> 200
POST /api/uploads -> 200
POST /api/sources -> 200
DELETE /api/sources/{id} -> 200
```

Final browser run recorded:

```text
React hook errors: 0
Runtime exceptions: 0
Network loading failures: 0
MissingAllowOrigin errors: 0
Browser upload: PASS
Browser source create/delete: PASS
Browser launch modal: opened and job submitted
```

## Network Evidence

The rejected protected responses did not include `Access-Control-Allow-Origin` because the auth middleware returned the `401` response before the CORS middleware could decorate it. The browser therefore exposed the response to JavaScript as a generic `Failed to fetch`.

The frontend also had no session bootstrap UI after removal of the bundled API key. Protected requests consequently had no cookie.

## Backend Evidence

Before remediation, backend logs showed the browser reaching the API while the browser reported CORS failure. After remediation, `debug_backend.log` recorded successful authenticated requests and CORS responses:

```text
POST /api/auth/session 200 OK
GET /api/jobs 200 OK
GET /api/sources 200 OK
GET /api/cameras 200 OK
GET /api/storage 200 OK
POST /api/uploads 200 OK
POST /api/sources 200 OK
DELETE /api/sources/{id} 200 OK
WebSocket /ws/jobs/{id} accepted
```

## Root Cause

Primary root cause:

```text
Auth middleware rejected unauthenticated requests before CORS headers were added,
and frontend had no valid session bootstrap flow after master-token removal.
```

Secondary root cause found during browser rerun:

```text
LaunchJobModal initialized selectedSourceId before async sources loaded,
so the modal could retain an empty source selection.
```

## Why API Health Was Still Green

`GET /api/health` is intentionally public and does not verify the operator session. The old header used that endpoint as its only connectivity signal, so it reported backend reachability rather than authenticated application readiness.

## Why Upload Failed

The upload request was blocked at the browser boundary by the missing CORS headers on the authentication rejection. It was not a multipart boundary bug. After session bootstrap, the browser sent a native `FormData` request and `/api/uploads` returned `200`.

## Why Sources/Sessions Failed

Both list requests were protected API calls without a cookie. Their `401` responses were hidden from frontend JavaScript by the missing CORS response headers, producing the generic error and empty fallback arrays.

## Camera Warning Analysis

The DirectShow warning was not the root cause. `/api/cameras` returned `200` and a camera list. The warnings came from probing unavailable camera indexes. Camera discovery is now performed once per mounted telemetry session instead of every telemetry interval. No camera warning caused the Source Fleet failure.

## Polling / Request Frequency Analysis

The original page had multiple browser targets open during debugging, which multiplied polling traffic. The application also polled jobs and sources every 2.5 seconds. Camera discovery was unnecessarily included in that repeating path. Camera discovery was removed from recurring polling and is cached for the mounted session.

## Files Changed

- `backend/app.py`
  - Added CORS headers to auth rejection responses.
  - Allowed CORS preflight requests through to `CORSMiddleware`.
  - Added authenticated `GET /api/auth/session` status endpoint.
- `frontend/src/api.ts`
  - Added session bootstrap and session status calls with `credentials: "include"`.
  - Added status/endpoint details to API errors.
  - Added credentials to worker log requests.
- `frontend/src/App.tsx`
  - Added operator session bootstrap screen.
  - Preserved React hook ordering across authenticated and unauthenticated renders.
- `frontend/src/hooks/useTelemetry.ts`
  - Added auth gating.
  - Cached camera discovery instead of probing on every refresh.
- `frontend/src/components/sources/LaunchJobModal.tsx`
  - Synchronizes the selected source after asynchronous source loading.
- `PIT_COOKIE_SECURE`
  - Local HTTP uses `false`; TLS deployments can set it to `true` without changing application code.
- `debug_backend.log`
- `debug_frontend.log`

## Regression Tests Added / Executed

Browser runtime checks:

- Session bootstrap and cookie session status
- Protected API list calls
- Browser `FormData` upload
- Source create/delete
- Launch modal source selection and job submission
- WebSocket/job telemetry path
- React console/runtime error capture

Automated checks:

```text
Frontend build: PASS
Python compile: PASS
25 tests collected: 20 passed, 5 skipped because live regression tests require a separately managed server
```

The five skipped tests are intentionally skipped when the test module detects no server; the browser session above independently exercised the live server.

## Remaining Issues

- DirectShow may still emit warnings for camera indexes that do not exist. This is an expected hardware-probe warning, not an application failure.
- The current operator session bootstrap requires the operator to enter the API key once. The key is not bundled, persisted, or placed in a URL.
- Internet/shared-untrusted-LAN deployment still requires HTTPS/WSS and stronger authorization controls.
