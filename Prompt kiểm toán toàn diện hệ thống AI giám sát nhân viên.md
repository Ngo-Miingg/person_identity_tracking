Bạn đang đóng vai trò:

**Senior Software Architect + Senior QA Engineer + AI/ML Systems Engineer + Security Reviewer + Adversarial Code Auditor.**

Bạn có quyền đọc và chạy TOÀN BỘ source code của dự án hệ thống giám sát nhân viên sử dụng AI.

Nhiệm vụ của bạn KHÔNG phải tiếp tục phát triển tính năng.

Nhiệm vụ của bạn là:

> **KIỂM TOÁN, TEST, PHÁ VỠ và XÁC MINH toàn bộ những gì đã được xây dựng để tìm ra lỗi logic, lỗi runtime, sai contract, race condition, dead code, fake UI, dữ liệu giả, chức năng chỉ tồn tại trên giao diện nhưng backend không hỗ trợ, lỗi AI pipeline, lỗi lifecycle và mọi rủi ro có thể khiến hệ thống chạy sai trong thực tế.**

---

# QUY TẮC SỐ 1 — KHÔNG TIN AI TRƯỚC

Một AI trước đó tuyên bố đã hoàn thành các phần sau:

- Chuẩn hóa `frontend/src/api.ts`
- nullable/optional fields:
  - `started_at`
  - `finished_at`
  - `return_code`
  - `error`
  - `cancel_requested_at`
- helper:
  - format bytes
  - duration
  - timestamp
  - absolute URL
  - WebSocket URL
- `useJobWebSocket.ts`
  - WebSocket `/ws/jobs/{id}`
  - tự fallback sang polling
- `useTelemetry.ts`
  - jobs
  - sources
  - cameras
  - `execution_lock`
- Dark Ops UI
- Live Operations
- Identity Hub
- Model Pipeline
- Forensic Archive
- Source Fleet
- camera discovery
- upload video 2GB
- inference job launch
- CUDA/CPU selection
- Gallery selection
- artifacts download
- worker.log viewer
- MJPEG
- snapshot fallback
- telemetry
- SQLite telemetry
- `PRAGMA integrity_check`
- face lifecycle
- IoU ambiguity alert
- AdaFace multi-angle
- OSNet wardrobe
- NPZ 512-D vector counting
- production frontend build
- CUDA environment check
- backend port 8000
- frontend port 5173.

**COI TẤT CẢ NHỮNG ĐIỀU TRÊN LÀ CLAIM CHƯA ĐƯỢC CHỨNG MINH.**

Bạn phải tìm evidence trong source hoặc chạy thực tế để xác minh từng claim.

Không được ghi `PASS` chỉ vì code tồn tại.

---

# QUY TẮC SỐ 2 — BUILD PASS KHÔNG CÓ NGHĨA LÀ HỆ THỐNG ĐÚNG

Không được coi:

```text
tsc -b
vite build
CHECK OK
server started
```

là bằng chứng hệ thống hoạt động đúng.

Phải test runtime và data flow thực tế.

Ví dụ:

```text
Frontend component exists
≠
Backend supports it
```

```text
API returns HTTP 200
≠
Response schema đúng
```

```text
WebSocket connects
≠
Realtime data đúng
```

```text
Model loads
≠
Pipeline inference đúng
```

```text
UI renders
≠
Data displayed chính xác
```

---

# MỤC TIÊU CUỐI CÙNG

Sau audit phải trả lời được:

1. Hệ thống có thực sự chạy end-to-end không?
2. Luồng dữ liệu có đúng như thiết kế không?
3. Có chức năng UI nào chỉ là “fake visualization” không?
4. Có UI nào đang hiển thị dữ liệu mà backend không thực sự cung cấp không?
5. API contract frontend/backend có khớp 100% không?
6. WebSocket có hoạt động thực tế không?
7. fallback polling có thực sự chạy đúng không?
8. job lifecycle có race condition không?
9. execution lock có thể bị deadlock/stale lock không?
10. camera/video có hoạt động trong điều kiện lỗi không?
11. AI model pipeline có đúng thứ tự không?
12. Identity logic có nguy cơ gán nhầm người không?
13. artifact/file path có bị sai không?
14. nullable state có gây crash UI không?
15. frontend có thể rơi vào stale state không?
16. backend restart có làm mất trạng thái không?
17. WebSocket disconnect/reconnect có gây duplicate event không?
18. polling và WebSocket có ghi đè dữ liệu của nhau không?
19. có memory leak / thread leak / process leak không?
20. có lỗi nào hiện tại build không phát hiện được không?

---

# PHASE 1 — REPOSITORY RECONNAISSANCE

Đọc toàn bộ repository trước.

Không chỉ đọc `PROJECT_HANDOFF.md`.

Phải đối chiếu tài liệu với source thật.

Đặc biệt kiểm tra:

```text
PROJECT_HANDOFF.md
backend/app.py
src/infer_engine.py
src/person_memory.py
src/identity_database.py

frontend/src/api.ts

frontend/src/hooks/useJobWebSocket.ts
frontend/src/hooks/useTelemetry.ts

frontend/src/**/LiveMonitorView.tsx
frontend/src/**/IdentityHubView.tsx
frontend/src/**/ModelPipelineView.tsx
frontend/src/**/ArchiveView.tsx
frontend/src/**/SourceManagerView.tsx
frontend/src/**/LaunchJobModal.tsx

start_console.ps1
check.py
```

và toàn bộ file mà các module trên import/call.

Tạo call graph chính của hệ thống.

---

# PHASE 2 — VERIFY CLAIMS

Tạo bảng:

| Claim | Evidence | Runtime Verified | Result | Problem |
|---|---|---|---|---|

Result chỉ được dùng:

```text
PASS
PARTIAL
FAIL
UNVERIFIED
MISLEADING
```

Ví dụ:

```text
Claim:
WebSocket tự fallback sang polling.

Evidence:
useJobWebSocket.ts ...

Runtime:
Kill WebSocket connection...

Result:
PASS / FAIL
```

Không được dựa vào tên function để kết luận.

---

# PHASE 3 — BACKEND API CONTRACT AUDIT

Tìm TẤT CẢ endpoint backend.

Tạo contract thật:

```text
METHOD
PATH
QUERY
BODY
RESPONSE
ERROR
NULLABLE
SIDE EFFECT
```

Sau đó đối chiếu từng API mà frontend gọi.

Phải phát hiện:

### Endpoint không tồn tại

Frontend gọi:

```text
/api/...
```

nhưng backend không có.

### HTTP method sai

Frontend:

```text
POST
```

Backend:

```text
PUT
```

### Field mismatch

Frontend:

```ts
job.startedAt
```

Backend:

```json
{
  "started_at": "..."
}
```

### Type mismatch

Frontend:

```ts
number
```

Backend có thể trả:

```text
null
```

### Enum mismatch

Frontend kỳ vọng:

```text
COMPLETED
RUNNING
FAILED
STOPPED
```

nhưng backend dùng status khác.

### URL mismatch

Kiểm tra:

```text
relative URL
absolute URL
artifact URL
MJPEG URL
snapshot URL
WebSocket URL
```

---

# PHASE 4 — TEST TOÀN BỘ JOB LIFECYCLE

Phải kiểm thử job từ đầu đến cuối.

Luồng tối thiểu:

```text
source created
→ job created
→ queued
→ execution lock acquired
→ worker started
→ inference running
→ telemetry updating
→ artifact generated
→ job completed
→ lock released
```

Test các trường hợp:

## Case A — Normal completion

Start job hợp lệ.

Xác minh:

- status transition
- timestamps
- PID/process
- stdout/log
- return code
- output
- artifacts
- lock.

---

## Case B — Job failure

Cố tình dùng input/model/config lỗi an toàn.

Kiểm tra:

```text
RUNNING → FAILED
```

Có set:

```text
finished_at
return_code
error
```

không?

Lock có release không?

---

## Case C — User stop

Start job.

Stop giữa chừng.

Kiểm tra:

```text
cancel_requested_at
status
child process
GPU memory
file handles
execution_lock
```

---

## Case D — Backend restart while job running

Kiểm tra behavior sau restart.

Có orphan process không?

Có stale lock không?

Backend có nghĩ job vẫn RUNNING không?

---

## Case E — Rapid double click

Gửi 2 request start gần như đồng thời.

Kiểm tra race condition.

Không chỉ gọi tuần tự.

Nếu có thể dùng concurrent requests.

Xác minh execution lock là atomic thật hay chỉ là boolean check:

```python
if not locked:
    locked = True
```

Nếu kiểu trên tồn tại thì phải flag race condition.

---

# PHASE 5 — EXECUTION LOCK ADVERSARIAL TEST

Kiểm tra toàn bộ lifecycle của:

```text
execution_lock
```

Các trường hợp:

```text
successful job
failed job
cancelled job
worker crash
exception
backend crash
process killed
invalid source
invalid model
GPU error
```

Phải đảm bảo lock luôn release.

Tìm:

```text
try
finally
```

hoặc cơ chế tương đương.

Nếu lock nằm trong memory process, ghi rõ:

```text
NOT SAFE ACROSS MULTIPLE BACKEND WORKERS
```

nếu đúng.

Nếu dùng Uvicorn nhiều worker, test ảnh hưởng.

---

# PHASE 6 — WEBSOCKET AUDIT

Kiểm tra:

```text
/ws/jobs/{id}
```

bằng runtime thực tế.

### Test 1

Connect với job hợp lệ.

Xác minh message thật.

Capture payload thực tế.

### Test 2

Connect job không tồn tại.

### Test 3

Disconnect network.

### Test 4

Reconnect.

### Test 5

Backend restart.

### Test 6

Job chuyển:

```text
RUNNING → COMPLETED
```

### Test 7

Job chuyển:

```text
RUNNING → FAILED
```

### Test 8

Unmount React component.

Kiểm tra socket có close không.

### Test 9

Đổi selected job nhanh liên tục.

Kiểm tra socket cũ có còn active không.

### Test 10

Multiple browser connections.

---

# PHASE 7 — POLLING FALLBACK AUDIT

Đây là khu vực rất dễ có bug.

Xác minh:

```text
WebSocket online
→ polling OFF

WebSocket disconnected
→ polling ON

WebSocket reconnected
→ polling OFF
```

Kiểm tra:

- duplicate requests
- multiple setInterval
- interval không cleanup
- socket stale closure
- request sau unmount
- overlapping polling
- race between WebSocket response and HTTP response.

Đặc biệt tìm lỗi kiểu:

```text
old polling result arrives AFTER newer websocket event
```

và ghi đè state mới bằng state cũ.

---

# PHASE 8 — REACT HOOK AUDIT

Audit:

```text
useJobWebSocket.ts
useTelemetry.ts
```

Tìm:

- stale closure
- thiếu dependency trong `useEffect`
- infinite rerender
- duplicated listener
- uncleared timeout
- uncleared interval
- WebSocket leak
- AbortController thiếu
- async update sau unmount
- dependency object thay đổi mỗi render
- race request
- inconsistent loading states.

Test component mount/unmount nhiều lần.

---

# PHASE 9 — LIVE MONITOR END-TO-END

Không chỉ render component.

Phải xác minh:

```text
backend
→ frame
→ stream
→ frontend
```

Kiểm tra:

## MJPEG

- URL đúng?
- browser đọc được?
- Content-Type đúng?
- stream đóng khi job kết thúc?
- stream lỗi UI xử lý thế nào?

## Snapshot fallback

Thực sự fallback được?

Hay chỉ có code nhưng không reachable?

Test bằng cách làm MJPEG fail.

---

# PHASE 10 — BOUNDING BOX VALIDATION

Đây là cực kỳ quan trọng.

Xác minh format backend thật:

```text
[x1,y1,x2,y2]
```

hay:

```text
[x,y,w,h]
```

hay normalized.

Sau đó xem frontend đang interpret thế nào.

Test frame resize.

Ví dụ backend inference:

```text
1920 x 1080
```

UI:

```text
960 x 540
```

Bounding box phải scale đúng.

Kiểm tra:

- aspect ratio
- object-fit contain
- letterboxing
- browser resize
- fullscreen
- different resolutions.

Flag nếu frontend vẽ trực tiếp pixel coordinate backend lên element đã resize.

---

# PHASE 11 — IoU AMBIGUITY CLAIM

AI trước tuyên bố:

```text
IoU >= 0.50
→ ambiguity alert
→ pause ReID memory update
```

Phải xác minh HAI vấn đề RIÊNG BIỆT.

## Visualization

Frontend có detect overlap và hiển thị banner?

## Actual AI behavior

Backend/inference engine có THỰC SỰ pause memory update hay không?

Nếu frontend chỉ hiển thị:

```text
"Memory update paused"
```

nhưng backend vẫn update memory thì đánh:

```text
CRITICAL — MISLEADING UI
```

Frontend không được mô tả hành vi AI không thực sự xảy ra.

---

# PHASE 12 — FACE STATE MACHINE AUDIT

Claim:

```text
ABSENT
→ TENTATIVE
→ VISIBLE
→ COASTING
→ LOST
```

Xác minh các state này:

- tồn tại trong backend?
- tồn tại trong inference?
- hay frontend tự suy diễn?

Xác minh transition rule.

Nếu frontend tạo lifecycle dựa trên heuristic riêng, phải ghi rõ.

Không được trình bày như internal state thực của model nếu backend không cung cấp.

---

# PHASE 13 — AI PIPELINE VALIDATION

Xác minh thực tế pipeline 5 model được tuyên bố:

```text
YOLO11s
BoT-SORT
SCRFD 10G
AdaFace IR50
OSNet x1.0
```

Phải trace source.

Với từng model:

```text
load
input
preprocessing
inference
postprocessing
threshold
output
caller
```

Sau đó xác minh thứ tự thực.

Không mặc định flow là:

```text
YOLO
→ SCRFD
→ AdaFace
→ OSNet
→ Fusion
```

nếu source không chạy đúng như vậy.

---

# PHASE 14 — IDENTITY ASSIGNMENT AUDIT

Đây là phần quan trọng nhất về correctness AI.

Trace:

```text
detection
→ track
→ face
→ embedding
→ person memory
→ candidate identity
→ fusion
→ assignment
```

Xác minh:

- unknown person
- same person returning
- temporary occlusion
- face unavailable
- only body available
- track ID switch
- two people crossing
- similar clothes
- wrong face detection
- multiple faces
- false positive detection.

---

# PHASE 15 — ID SEMANTICS

Xác minh rõ:

```text
track_id
person_id
identity_id
employee_id
observation_id
assignment_id
```

hoặc ID tương đương.

Phải kiểm tra frontend có đang dùng sai ID không.

Ví dụ:

```text
track_id
```

KHÔNG được coi là stable employee identity nếu tracker có thể tạo ID mới.

---

# PHASE 16 — ADaFACE MULTI-ANGLE MATRIX

Claim:

```text
left yaw < -0.25
front
right yaw > +0.25
```

Phải xác minh:

- source có yaw không?
- yaw unit là gì?
- value range?
- threshold thực sự là ±0.25?
- yaw được lưu ở đâu?
- API có trả yaw?
- frontend tự tính hay backend trả?

Nếu đây chỉ là logic UI invented:

```text
MISLEADING
```

---

# PHASE 17 — OSNET BODY WARDROBE

Xác minh:

- OSNet crop thực sự được lưu?
- crop path tồn tại?
- frontend fetch được?
- crop thuộc đúng identity?
- có body embedding metadata?
- có stale files?
- có cleanup?

Nếu frontend gọi nó là “OSNet wardrobe” nhưng chỉ đang hiển thị image crop không có liên hệ với OSNet, ghi rõ.

---

# PHASE 18 — NPZ VECTOR AUDIT

Claim:

```text
đếm chính xác vector 512-D trong .npz
```

Phải mở file thực.

Xác minh:

```text
shape
dtype
keys
number of embeddings
```

Không được giả định mọi array trong `.npz` đều là embedding.

Test malformed `.npz`.

Test empty `.npz`.

Test array dimension không phải 512.

Frontend/backend có crash không?

---

# PHASE 19 — SQLITE IDENTITY DATABASE

Xác minh các bảng được tuyên bố:

```text
tracklets
detections
observations
assignments
fusion_decisions
```

Chạy:

```sql
PRAGMA integrity_check;
```

nhưng KHÔNG dừng ở đây.

Kiểm tra:

```text
schema
FK
indexes
NULL
orphan rows
duplicate rows
transaction handling
concurrent access
locking
```

Test đọc DB khi inference đang ghi.

Kiểm tra nguy cơ:

```text
database is locked
```

---

# PHASE 20 — FUSION DECISION VALIDATION

Nếu UI hiển thị:

> lý do gán ID

thì xác minh dữ liệu đó đến từ backend/DB thực.

Không cho phép frontend tự viết explanation từ final score rồi gọi là “reason backend”.

Kiểm tra:

```text
face score
body score
temporal evidence
confidence
decision
candidate IDs
```

nếu tồn tại.

---

# PHASE 21 — FORENSIC ARCHIVE

Test mỗi artifact:

```text
tracks.csv
identity.sqlite
person_memory.json
_identity.mp4
worker.log
```

Với từng artifact:

1. job chạy xong có thật sự được tạo?
2. path đúng?
3. API trả đúng?
4. download được?
5. file zero-byte?
6. browser download đúng filename?
7. missing file xử lý thế nào?
8. path traversal vulnerability?

---

# PHASE 22 — WORKER.LOG

Kiểm tra:

- Unicode
- file lớn
- log đang được ghi
- log missing
- permission error
- XSS nếu log render trong HTML
- memory issue nếu frontend load toàn bộ file hàng trăm MB.

Nếu API đọc toàn bộ log vào memory:

flag performance risk.

---

# PHASE 23 — VIDEO UPLOAD

Claim:

```text
upload tới 2GB
```

Không được tin constant frontend.

Kiểm tra toàn stack:

```text
browser
→ Vite
→ HTTP
→ backend
→ framework limit
→ disk
→ filesystem
```

Test:

```text
0 byte
small file
wrong extension
fake extension
large file
same filename
Unicode filename
very long filename
```

Kiểm tra path traversal:

```text
../../file
```

Kiểm tra overwrite.

Kiểm tra disk exhaustion risk.

---

# PHASE 24 — CAMERA DISCOVERY

Claim:

```text
DirectShow index 0 → 5
```

Xác minh:

- chạy ở backend hay browser?
- OpenCV backend nào?
- DirectShow có đúng Windows không?
- camera đang bị app khác chiếm
- index unavailable
- index 6+ thì sao?
- camera trả frame false?
- permission denied?
- discovery có treo request không?

Kiểm tra release:

```python
cap.release()
```

cho mọi camera test.

---

# PHASE 25 — CUDA / CPU

Test:

```text
CUDA available
CUDA unavailable
invalid device
CPU explicitly selected
```

Xác minh UI selection được truyền xuống inference thật.

Không chỉ đổi label.

Trace:

```text
Frontend
→ request
→ backend
→ worker command
→ infer_engine
→ model device
```

Nếu UI chọn CPU nhưng model vẫn `.cuda()`, flag CRITICAL.

---

# PHASE 26 — MODEL PATH / GALLERY PATH

Test:

```text
valid path
missing path
relative path
absolute path
spaces
Unicode
nonexistent directory
file instead of directory
```

Kiểm tra shell escaping.

Đặc biệt Windows PowerShell.

Tìm command injection nếu backend nối command bằng string.

---

# PHASE 27 — PROCESS SPAWNING AUDIT

Xem backend chạy inference bằng:

```text
subprocess
Popen
shell=True
os.system
PowerShell
cmd
```

Kiểm tra:

- quoting
- path spaces
- command injection
- process cleanup
- zombie process
- stdout pipe deadlock
- stderr pipe deadlock
- child process tree termination.

Nếu chỉ kill parent nhưng model process con tiếp tục chạy GPU:

flag CRITICAL.

---

# PHASE 28 — SOURCE FILE LIFECYCLE

Test:

```text
upload
register
start job
delete/rename file
run job
```

Kiểm tra source record trỏ tới file không còn tồn tại.

Kiểm tra duplicate source.

---

# PHASE 29 — FRONTEND NULL SAFETY

Dùng runtime payload có:

```json
{
  "started_at": null,
  "finished_at": null,
  "return_code": null,
  "error": null,
  "cancel_requested_at": null
}
```

Xác minh mọi component render được.

Không chỉ TypeScript.

Test:

```text
undefined
null
empty string
missing field
```

nếu backend có thể xảy ra.

---

# PHASE 30 — TIME / TIMESTAMP

Xác minh:

```text
UTC?
local time?
ISO 8601?
timezone offset?
naive datetime?
```

Kiểm tra frontend formatter.

Đặc biệt:

```text
started_at
finished_at
cancel_requested_at
```

Không để UI hiển thị sai timezone.

---

# PHASE 31 — LARGE DATA TEST

Test với:

```text
100 jobs
1,000 jobs
large log
large detection list
many identity crops
many artifacts
```

Kiểm tra:

- rendering
- API latency
- memory
- polling traffic.

---

# PHASE 32 — REACT UI ERROR STATES

Mỗi view phải test:

```text
loading
success
empty
HTTP 400
HTTP 404
HTTP 409
HTTP 500
network offline
backend unavailable
malformed JSON
slow response
```

UI không được blank screen.

---

# PHASE 33 — ROUTING

Test:

- refresh trực tiếp từng URL
- browser back
- browser forward
- invalid route
- selected job mất sau refresh
- selected session không tồn tại.

---

# PHASE 34 — SERVICE STARTUP

Test từ trạng thái:

```text
không có backend
không có frontend
không có venv active
```

Chạy `start_console.ps1`.

Xác minh:

- tìm Python đúng
- không phụ thuộc terminal cũ
- backend boot
- frontend boot
- port conflict
- venv missing
- dependency missing.

---

# PHASE 35 — PORT CONFLICT

Cố tình chiếm:

```text
8000
5173
```

Xem script xử lý thế nào.

Không được báo “system running” nếu process startup fail.

---

# PHASE 36 — SECURITY AUDIT NHẸ NHƯNG BẮT BUỘC

Kiểm tra:

```text
CORS *
path traversal
arbitrary file read
arbitrary file download
command injection
upload validation
WebSocket auth
API auth
shell=True
untrusted gallery path
camera path injection
log XSS
```

Không thực hiện hành động phá hoại.

Chỉ dùng payload an toàn.

---

# PHASE 37 — FALSE UI / MISLEADING UI AUDIT

Đây là phần đặc biệt quan trọng.

Tìm tất cả những thứ UI hiển thị như:

```text
CUDA active
model running
face verified
ReID confirmed
memory paused
ambiguity detected
SQLite healthy
model size
vector count
face lifecycle
fusion reason
camera status
API online
global lock
```

Với từng thông tin, hỏi:

> Dữ liệu này đến từ BACKEND THẬT, hay chỉ được frontend hardcode / derive / giả lập?

Tạo bảng:

| UI Information | Data Source | Truthful? | Risk |
|---|---|---|---|

Nếu hardcode:

```text
STATIC
```

Nếu suy diễn:

```text
DERIVED
```

Nếu backend cung cấp:

```text
BACKEND-GROUNDED
```

Nếu misleading:

```text
MISLEADING
```

---

# PHASE 38 — HARDCODE SEARCH

Search toàn frontend/backend cho:

```text
RTX 3050
CUDA
YOLO11s
SCRFD
AdaFace
OSNet
512
0.50
0.25
COMPLETED
RUNNING
FAILED
STOPPED
8000
5173
```

Xác minh giá trị nào:

- configuration thực
- data backend
- hay hardcoded presentation.

---

# PHASE 39 — DEAD CODE

Tìm:

- component không được render
- hook không được sử dụng
- API function không được gọi
- backend route không reachable
- helper không dùng
- obsolete files.

Không tính code tồn tại là functionality nếu unreachable.

---

# PHASE 40 — EXCEPTION PATH AUDIT

Tìm tất cả:

```python
try:
    ...
except:
    pass
```

hoặc:

```python
except Exception:
```

và kiểm tra có nuốt lỗi không.

Tìm frontend:

```ts
catch(() => {})
```

hoặc catch không báo user.

---

# PHASE 41 — RESOURCE CLEANUP

Kiểm tra tất cả resource:

```text
VideoCapture
VideoWriter
SQLite connections
files
WebSocket
timers
threads
processes
GPU tensors
queues
```

Phải được cleanup ở mọi exception path.

---

# PHASE 42 — MULTIPLE RUN TEST

Chạy:

```text
job #1
job #2
job #3
```

liên tục.

Không chỉ test một lần sau fresh startup.

Tìm:

- state leak
- old identities
- stale person memory
- reused DB connection
- leftover video handles
- stale WebSocket.
  
---

# PHASE 43 — CLEAN-ENVIRONMENT TEST

Không được chỉ test environment hiện tại đã có dependency.

Nếu khả thi, đọc dependency manifests và xác minh một máy mới có thể setup từ documented command.

Tìm dependency được import nhưng không khai báo.

---

# PHASE 44 — TEST AUTOMATION

Sau khi manual/adversarial audit, bổ sung automated tests cho các bug/risk quan trọng nếu repository cho phép.

Ưu tiên:

```text
API contract tests
job lifecycle tests
lock tests
WebSocket tests
polling tests
frontend hook tests
path tests
state transition tests
```

Không được sửa behavior chỉ để test pass nếu behavior chưa được xác nhận là đúng.

---

# PHASE 45 — KHÔNG SỬA NGAY KHI CHƯA AUDIT XONG

Trong vòng audit đầu tiên:

**KHÔNG sửa code ngay khi thấy lỗi.**

Đầu tiên phải thu thập đầy đủ findings.

Sau khi audit hoàn tất mới chia thành:

```text
Critical
High
Medium
Low
```

Sau đó mới đề xuất fix.

Mục tiêu là tránh sửa lỗi A làm che mất lỗi B.

---

# SEVERITY

## CRITICAL

Ví dụ:

- sai identity
- process chạy ngầm không kiểm soát
- execution lock deadlock
- command injection
- arbitrary file access
- frontend hiển thị trạng thái AI sai với backend
- dữ liệu người A hiện thành người B.

## HIGH

- job lifecycle sai
- WebSocket state sai
- artifact không tải được
- camera không release
- DB corruption/lock
- CPU/GPU selection không có tác dụng.

## MEDIUM

- stale UI
- incorrect formatting
- recovery kém
- memory/performance issue vừa phải.

## LOW

- cosmetic
- text
- UX nhỏ.

---

# OUTPUT BẮT BUỘC

Tạo file:

```text
SYSTEM_AUDIT.md
```

Cấu trúc bắt buộc:

# System Audit

## 1. Executive Summary

Trả lời ngắn:

```text
Production ready: YES / NO
End-to-end verified: YES / PARTIAL / NO
Critical issues: N
High issues: N
Medium issues: N
Low issues: N
```

---

# 2. What Was Actually Tested

Phân biệt:

```text
STATIC ANALYSIS
RUNTIME TEST
INTEGRATION TEST
NOT TESTED
```

---

# 3. Claim Verification

Toàn bộ claim của AI trước.

---

# 4. End-to-End Flow Verification

Viết flow thật mà bạn đã xác minh:

```text
UI
→ Backend
→ Worker
→ AI
→ DB/files
→ Backend
→ WebSocket/API
→ UI
```

Đánh PASS/FAIL từng đoạn.

---

# 5. Critical Findings

Mỗi lỗi phải dùng format:

## BUG-001 — Title

**Severity:** CRITICAL

**Location:**

```text
file:
line/function:
```

**Observed behavior:**

**Expected behavior:**

**How to reproduce:**

```text
...
```

**Root cause:**

**Impact:**

**Evidence:**

**Recommended fix:**

---

# 6. High Findings

Cùng format.

---

# 7. Medium Findings

---

# 8. Low Findings

---

# 9. Frontend ↔ Backend Contract Matrix

| Feature | Frontend | Backend | Match | Runtime Tested |
|---|---|---|---|---|

---

# 10. AI Pipeline Verification

| Stage | Model | Source | Runtime | Result |
|---|---|---|---|---|

---

# 11. Job State Machine

Vẽ state machine thực tế.

```mermaid
stateDiagram-v2
...
```

Nếu implementation có transition sai, đánh dấu.

---

# 12. WebSocket State Machine

```mermaid
stateDiagram-v2
...
```

---

# 13. Resource Lifecycle

Ghi:

```text
camera
worker
GPU
socket
timer
DB
file
```

và cleanup behavior.

---

# 14. Misleading UI Findings

Đây là phần bắt buộc.

Liệt kê mọi thông tin UI không phản ánh trực tiếp hệ thống thực.

---

# 15. Security Findings

---

# 16. Performance Risks

---

# 17. Race Conditions

---

# 18. Data Integrity Risks

---

# 19. Test Results

Bảng:

| Test | Expected | Actual | Result |
|---|---|---|---|

---

# 20. Untested Areas

Không được giấu phần chưa test.

Nếu không thể test camera thật hoặc input nào đó:

ghi rõ.

---

# 21. Recommended Fix Order

Sắp xếp theo:

```text
P0
P1
P2
P3
```

---

# 22. Final Verdict

Trả lời:

### Có thể demo không?

```text
YES / NO
```

### Có thể bàn giao cho người khác không?

```text
YES / NO
```

### Có thể dùng production không?

```text
YES / NO
```

### Có nguy cơ hiển thị dữ liệu sai không?

```text
YES / NO
```

### Có nguy cơ identity sai không?

```text
YES / NO / NOT VERIFIED
```

### Có race condition không?

```text
YES / NO / NOT VERIFIED
```

### Có resource leak không?

```text
YES / NO / NOT VERIFIED
```

---

# PHASE CUỐI — FIX VERIFICATION

Sau khi hoàn thành `SYSTEM_AUDIT.md`:

Nếu bạn được phép chỉnh source, hãy sửa lần lượt:

```text
P0 → P1 → P2
```

Sau MỖI fix:

1. chạy lại test gây ra bug;
2. chạy regression test liên quan;
3. kiểm tra không phá flow khác.

Không được ghi:

```text
FIXED
```

chỉ vì đã sửa code.

Chỉ ghi `FIXED` khi runtime test sau fix PASS.

Cập nhật finding:

```text
Status: FIXED + VERIFIED
```

hoặc:

```text
Status: FIX ATTEMPTED BUT NOT VERIFIED
```

---

# YÊU CẦU ĐẶC BIỆT

Nếu phát hiện một tính năng frontend trông rất đẹp nhưng không được backend/model support thực sự, phải ưu tiên báo lỗi.

Ví dụ:

```text
UI: "ReID Memory Paused"

Backend:
không hề pause memory.

Verdict:
CRITICAL MISLEADING UI
```

Hoặc:

```text
UI: CUDA RTX 3050

Data source:
hardcoded string.

Verdict:
MISLEADING TELEMETRY
```

Hoặc:

```text
UI:
Face state = COASTING

Backend:
không có concept COASTING.

Verdict:
FRONTEND-DERIVED STATE
```

Không được để UI mô tả một trạng thái nội bộ AI như sự thật nếu source AI không cung cấp trạng thái đó.

---

# TIÊU CHÍ PASS CUỐI CÙNG

Chỉ được kết luận hệ thống đạt khi đã chứng minh được:

```text
Source
→ Job
→ Process
→ AI inference
→ Tracking
→ Identity
→ Persistence
→ API
→ WebSocket
→ Frontend
```

hoạt động end-to-end.

Và đã test ít nhất:

```text
normal path
failure path
cancel path
disconnect path
restart path
invalid input path
concurrency path
```

Không được kết luận “hoàn thành” chỉ dựa trên happy path.

---

# CÂU LỆNH CUỐI CÙNG

Hãy bắt đầu bằng việc:

1. đọc repository;
2. xác định architecture thực;
3. lập danh sách các claim cần chứng minh;
4. audit code;
5. chạy runtime tests;
6. cố tình tạo các failure scenario an toàn;
7. ghi lại evidence;
8. tạo `SYSTEM_AUDIT.md`;
9. chỉ sau đó mới sửa lỗi;
10. rerun toàn bộ regression test.

**Đừng cố chứng minh code là đúng. Hãy cố chứng minh code là sai.**

Chỉ khi bạn đã cố phá hệ thống bằng các tình huống hợp lý mà không phá được, mới được đánh `PASS`.

**Không tin README. Không tin PROJECT_HANDOFF.md. Không tin summary của AI trước. Không tin tên function. Không tin UI. Chỉ tin source code + observable runtime behavior + reproducible evidence.**