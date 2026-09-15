export const API = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000/api";
export const API_ORIGIN = API.replace(/\/api$/, "");

// Operator token state held in memory only (never written to localStorage or bundled as plain text)
let inMemoryOperatorToken: string | null = null;

export function setOperatorToken(token: string | null): void {
  inMemoryOperatorToken = token;
}

export function getOperatorToken(): string | null {
  return inMemoryOperatorToken;
}

export async function createSession(operatorToken: string): Promise<void> {
  const response = await fetch(`${API}/auth/session`, {
    method: "POST",
    headers: { Authorization: `Bearer ${operatorToken}` },
    credentials: "include",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Session bootstrap failed (${response.status})`);
  }
  setOperatorToken(null);
}

export async function hasSession(): Promise<boolean> {
  const response = await fetch(`${API}/auth/session`, { credentials: "include" });
  return response.ok;
}

export function getWsUrl(jobId: string): string {
  const origin = API_ORIGIN.replace(/^http/, "ws");
  // If in-memory token exists (for standalone test), pass as ticket, else rely on HttpOnly Cookie
  const token = inMemoryOperatorToken;
  const suffix = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${origin}/ws/jobs/${encodeURIComponent(jobId)}${suffix}`;
}

export function getAbsoluteUrl(path: string | null | undefined): string {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://") || path.startsWith("ws://") || path.startsWith("wss://")) {
    return path;
  }
  const base = `${API_ORIGIN}${path.startsWith("/") ? "" : "/"}${path}`;
  // When browser has HttpOnly cookie or proxy handles auth, no secret is placed in URL
  if (inMemoryOperatorToken) {
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}token=${encodeURIComponent(inMemoryOperatorToken)}`;
  }
  return base;
}

export function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatTimestamp(epochSeconds?: number | null): string {
  if (!epochSeconds) return "—";
  const date = new Date(epochSeconds * 1000);
  return date.toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function formatDuration(seconds?: number | null): string {
  if (seconds === undefined || seconds === null || seconds < 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m === 0) return `${s}s`;
  const h = Math.floor(m / 60);
  if (h === 0) return `${m}m ${s}s`;
  return `${h}h ${m % 60}m ${s}s`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (inMemoryOperatorToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${inMemoryOperatorToken}`);
  }
  const response = await fetch(`${API}${path}`, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent("pit:unauthorized"));
    }
    const text = await response.text();
    let message = text;
    try {
      const json = JSON.parse(text);
      if (json.detail) message = json.detail;
    } catch {
      // ignore
    }
    const error = new Error(message || `Request failed with status ${response.status}`) as Error & { status?: number; endpoint?: string };
    error.status = response.status;
    error.endpoint = path;
    throw error;
  }
  return response.json();
}

export type JobMedia = {
  state: "LIVE" | "READY" | "PARTIAL" | "UNAVAILABLE" | string;
  consistency: "LIVE_PROVISIONAL" | "FINAL_RECONCILED" | "PARTIAL_UNRECONCILED" | string;
  live_url: string | null;
  snapshot_url: string;
  playback_url: string | null;
  download_url: string | null;
  warning: string | null;
};

export type JobArtifact = {
  name: string;
  size: number;
  state: "READY" | "PARTIAL" | "WRITING" | string;
  role: "download" | "evidence" | string;
  playback: boolean | null;
};

export type JobProgress = {
  rows: number;
  frames: number;
  phase: "queued" | "running" | "finished" | "failed" | "stopped" | string;
};

export type Job = {
  id: string;
  name: string;
  source: string;
  source_label: string;
  source_kind: "upload" | "webcam" | "rtsp" | string;
  preview_url: string | null;
  status: "QUEUED" | "RUNNING" | "CANCEL_REQUESTED" | "COMPLETED" | "FAILED" | "STOPPED" | string;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  return_code: number | null;
  error: string | null;
  cancel_requested_at: number | null;
  pid?: number | null;
  updated_at?: number | null;
  progress: JobProgress;
  artifacts: JobArtifact[];
  media: JobMedia;
};

export type Source = {
  id: string;
  name: string;
  kind: "upload" | "webcam" | "rtsp";
  uri: string;
  location: string;
  enabled: boolean;
};

export type Camera = {
  index: number;
  label: string;
  width: number;
  height: number;
};

export type IdentityEvent = {
  tracklet_id?: number | null;
  old_identity_id?: number | string | null;
  new_identity_id?: number | string | null;
  frame: number;
  event: string;
  evidence_json?: string | Record<string, unknown>;
  created_at?: string;
  [key: string]: unknown;
};

export type Summary = {
  identities: string[];
  tracks: number;
  events: number;
  states: Record<string, number>;
  recent_events: IdentityEvent[];
};

export type PrototypeInfo = {
  pose: string;
  quality: number;
  count: number;
};

export type TrackSummary = {
  camera: string;
  track_id: number;
  person_id: string;
  bind_reason: string;
  first_frame: number;
  last_frame: number;
  confirmed_employee: string | null;
  final_state: "CONFIRMED" | "UNIDENTIFIED" | "UNKNOWN" | string;
  face_prototypes: PrototypeInfo[];
  body_prototypes: number;
  online_face_observations: number;
  online_body_observations: number;
  face_observations?: number;
  body_observations?: number;
  ambiguous_frames: number;
  strong_face_conflict: boolean;
};

export type MemorySample = {
  pose?: "front" | "left" | "right" | string;
  tier?: "strong" | "support" | "weak" | "reject" | string;
  quality: number;
  support?: number;
  core?: boolean;
  first_frame?: number;
  last_frame?: number;
  sample_file?: string | null;
  image_url: string;
};

export type IdentityProfile = {
  person_id: string;
  employee_id: string | null;
  maturity: "UNBOUND" | "SEED" | "CANDIDATE" | "STABLE" | string;
  confidence: number;
  face_observations: number;
  body_observations: number;
  face_anchor_count: number;
  conflict_count: number;
  members: { camera: string; track_id: number }[];
  face_vectors: number;
  body_vectors: number;
  face_memory: MemorySample[];
  body_memory: MemorySample[];
};

export type IdentityMemory = {
  job_id: string;
  mode: string;
  profiles: IdentityProfile[];
};

export type JobDetails = {
  job_id: string;
  summary: Summary;
  identities: IdentityProfile[];
  tracks: TrackSummary[];
  tracklets?: TrackSummary[];
  events: IdentityEvent[];
  database: {
    integrity: string;
    tables: {
      tracklets?: number;
      detections?: number;
      observations?: number;
      assignments?: number;
      fusion_decisions?: number;
      identity_events?: number;
      [key: string]: number | undefined;
    };
    error?: string;
  };
};

export type LiveTelemetryTrack = {
  track_id: number;
  person_id: string | null;
  identity_state: string | null;
  face_state: "VISIBLE" | "COASTING" | "TENTATIVE" | "ABSENT" | "LOST" | string;
  face_decision?: string;
  face_candidate_votes?: number;
  face_candidate_needed?: number;
  ambiguous: boolean;
};

export type LiveTelemetry = {
  job_id: string;
  status: string;
  available: boolean;
  frame: number;
  camera: string | null;
  timestamp: number | null;
  tracks_count: number;
  has_ambiguity: boolean;
  tracks: LiveTelemetryTrack[];
};

export type BiometricEvent = {
  event_id: string;
  job_frame: number;
  camera: string | null;
  track_id: number;
  person_id: string | null;
  identity_state: string;
  face_state: string;
  face_decision: string;
  face_candidate_votes: number;
  face_candidate_needed: number;
  ambiguous: boolean;
  timestamp: number | null;
};

export type StorageMetrics = {
  disk_total_bytes: number;
  disk_used_bytes: number;
  disk_free_bytes: number;
  uploads_size_bytes: number;
  jobs_size_bytes: number;
  retention: {
    enabled: boolean;
    days: number;
    max_gb: number;
  };
};

export type TrackRow = {
  camera: string;
  frame: string;
  track_id: string;
  x1: string;
  y1: string;
  x2: string;
  y2: string;
  conf: string;
  memory_ambiguous: string;
  face_state: string;
  face_score: string;
  face_x1: string;
  face_y1: string;
  face_x2: string;
  face_y2: string;
  online_person_id: string;
  online_memory_state: string;
  person_id: string;
  person_bind_reason: string;
  memory_maturity: string;
  memory_confidence: string;
  face_id_frame: string;
  face_id_person: string;
  face_id_decision: string;
  face_id_accepted: string;
  face_id_top1: string;
  face_id_top1_score: string;
  face_id_top2: string;
  face_id_top2_score: string;
  face_id_margin: string;
  face_id_candidate_votes: string;
  face_id_candidate_needed: string;
  face_id_pose: string;
  face_id_tier: string;
  face_id_quality: string;
  face_id_age_frames: string;
  identity: string;
  identity_state: string;
  fusion_identity: string;
  fusion_state: string;
  fusion_reason: string;
  fusion_face_score: string;
  fusion_body_score: string;
  fusion_score: string;
  fusion_margin: string;
  [key: string]: string;
};

export type CreateJobPayload = {
  source_id?: string | null;
  source?: string | null;
  name?: string;
  device?: string;
  gallery?: string | null;
  canonical_db?: string | null;
  extra_args?: string[];
};

export const api = {
  health: () => request<{ ok: boolean; service: string; jobs: number }>("/health"),
  sources: () => request<Source[]>("/sources"),
  cameras: () => request<Camera[]>("/cameras"),
  addSource: (body: Omit<Source, "id">) =>
    request<Source>("/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteSource: (id: string) => request<{ ok: boolean }>(`/sources/${id}`, { method: "DELETE" }),
  jobs: () => request<Job[]>("/jobs"),
  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  createJob: (body: CreateJobPayload) =>
    request<Job>("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  stopJob: (id: string) => request<Job>(`/jobs/${id}/stop`, { method: "POST" }),
  retryJob: (id: string) => request<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  summary: (id: string) => request<Summary>(`/jobs/${id}/summary`),
  identities: (id: string) => request<IdentityMemory>(`/jobs/${id}/identities`),
  details: (id: string) => request<JobDetails>(`/jobs/${id}/details`),
  telemetry: (id: string) => request<LiveTelemetry>(`/jobs/${id}/telemetry`),
  biometricEvents: (id: string, limit = 200) => request<{ job_id: string; events: BiometricEvent[] }>(`/jobs/${id}/events?limit=${limit}`),
  storage: () => request<StorageMetrics>("/storage"),
  pruneStorage: (dryRun = true) =>
    request<{ pruned_jobs_count: number; freed_bytes: number }>(
      `/storage/prune?dry_run=${dryRun}`,
      { method: "POST" }
    ),
  tracks: (id: string, limit = 200) => request<TrackRow[]>(`/jobs/${id}/tracks?limit=${limit}`),
  log: async (id: string, tail = 1000, full = false): Promise<string> => {
    const res = await fetch(`${API}/jobs/${id}/log?tail=${tail}&full=${full}`, { credentials: "include" });
    if (!res.ok) throw new Error(`Log request failed (${res.status})`);
    return res.text();
  },
  upload: async (file: File): Promise<{ id: string; name: string; preview_url: string }> => {
    const form = new FormData();
    form.append("file", file);
    return request<{ id: string; name: string; preview_url: string }>("/uploads", {
      method: "POST",
      body: form,
    });
  },
};
