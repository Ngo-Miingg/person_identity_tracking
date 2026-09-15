import React, { useState, useEffect, useRef } from "react";
import { Job, api, getAbsoluteUrl, Summary, TrackRow, LiveTelemetry, IdentityMemory, IdentityProfile, BiometricEvent } from "../../api";
import { useJobWebSocket } from "../../hooks/useJobWebSocket";
import "./live.css";

interface LiveMonitorViewProps {
  selectedJob: Job | null;
  onJobUpdated?: () => void;
  onSelectJobId?: (id: string) => void;
}

type LivePersonEvent = {
  key: string;
  trackId: number;
  personId: string | null;
  identityState: string;
  faceState: string;
  ambiguous: boolean;
  frame: number;
  timestamp: number | null;
};

function toLiveEvent(event: BiometricEvent): LivePersonEvent {
  return {
    key: event.event_id,
    trackId: event.track_id,
    personId: event.person_id,
    identityState: event.identity_state,
    faceState: event.face_state,
    ambiguous: event.ambiguous,
    frame: event.job_frame,
    timestamp: event.timestamp,
  };
}

function mergeLiveEvents(previous: LivePersonEvent[], incoming: LivePersonEvent[]): LivePersonEvent[] {
  const byKey = new Map<string, LivePersonEvent>();
  for (const event of [...previous, ...incoming]) byKey.set(event.key, event);
  return [...byKey.values()].sort((left, right) => right.frame - left.frame).slice(0, 40);
}

export const LiveMonitorView: React.FC<LiveMonitorViewProps> = ({ selectedJob, onJobUpdated, onSelectJobId }) => {
  const { job: wsJob } = useJobWebSocket(selectedJob?.id);
  const currentJob = wsJob?.id === selectedJob?.id ? wsJob : selectedJob;

  const [summary, setSummary] = useState<Summary | null>(null);
  const [recentTracks, setRecentTracks] = useState<TrackRow[]>([]);
  const [telemetry, setTelemetry] = useState<LiveTelemetry | null>(null);
  const [liveEvents, setLiveEvents] = useState<LivePersonEvent[]>([]);
  const [identityMemory, setIdentityMemory] = useState<IdentityMemory | null>(null);
  const [identityLoading, setIdentityLoading] = useState<boolean>(false);
  const [identityError, setIdentityError] = useState<string | null>(null);
  const [selectedEventKey, setSelectedEventKey] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<boolean>(false);
  const [streamRetryCount, setStreamRetryCount] = useState<number>(0);
  const [useSnapshotFallback, setUseSnapshotFallback] = useState<boolean>(false);
  const [stopping, setStopping] = useState<boolean>(false);
  const [retrying, setRetrying] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [playbackRate, setPlaybackRate] = useState<number>(1);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const isRunning = currentJob?.status === "RUNNING" || currentJob?.status === "CANCEL_REQUESTED";

  useEffect(() => {
    setStreamError(false);
    setStreamRetryCount(0);
    setUseSnapshotFallback(false);
    setSummary(null);
    setRecentTracks([]);
    setTelemetry(null);
    setLiveEvents([]);
    setIdentityMemory(null);
    setIdentityError(null);
    setSelectedEventKey(null);
    setRefreshKey((key) => key + 1);
    setPlaybackRate(1);
  }, [selectedJob?.id]);

  useEffect(() => {
    const jobId = currentJob?.id;
    if (!jobId) return;
    let cancelled = false;
    api.biometricEvents(jobId, 200)
      .then((data) => {
        if (!cancelled) setLiveEvents((previous) => mergeLiveEvents(previous, data.events.map(toLiveEvent)));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [currentJob?.id]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = playbackRate;
  }, [playbackRate]);

  useEffect(() => {
    if (!streamError || !isRunning) return;
    const timer = window.setTimeout(() => {
      setStreamError(false);
      setStreamRetryCount((count) => count + 1);
      setRefreshKey((key) => key + 1);
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [isRunning, streamError]);

  // Browsers can keep an MJPEG connection open while its multipart decoder has
  // silently stopped painting. Periodically remount the stream without waiting
  // for an onError event; the latest snapshot remains the fallback.
  useEffect(() => {
    if (!isRunning) return;
    const timer = window.setInterval(() => {
      setStreamRetryCount((count) => count + 1);
      setRefreshKey((key) => key + 1);
    }, 30000);
    return () => window.clearInterval(timer);
  }, [isRunning]);

  useEffect(() => {
    const jobId = currentJob?.id;
    if (!jobId) return;
    let cancelled = false;
    let timer: number | null = null;
    const fetchDiagnostics = async () => {
      const [sum, tracks, telem] = await Promise.all([
        api.summary(jobId).catch(() => null),
        api.tracks(jobId, 25).catch(() => [] as TrackRow[]),
        api.telemetry(jobId).catch(() => null),
      ]);
      if (cancelled || currentJob?.id !== jobId) return;
      setSummary(sum);
      setRecentTracks(tracks);
      setTelemetry(telem);
      if (telem?.tracks?.length) {
        setLiveEvents((previous) => {
          const current = telem.tracks.map((track) => ({
            key: `${jobId}-${track.track_id}-${telem.frame}`,
            trackId: track.track_id,
            personId: track.person_id,
            identityState: track.identity_state || "UNIDENTIFIED",
            faceState: track.face_state,
            ambiguous: track.ambiguous,
            frame: telem.frame,
            timestamp: telem.timestamp,
          }));
          return mergeLiveEvents(previous, current.map((event) => ({
            ...event,
            key: `${jobId}:${telem.camera || "camera"}:${event.trackId}:${event.frame}`,
          })));
        });
      }
      timer = window.setTimeout(fetchDiagnostics, isRunning ? 1000 : 6000);
    };
    fetchDiagnostics();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [currentJob?.id, isRunning]);

  const selectedEvent = liveEvents.find((event) => event.key === selectedEventKey) || null;
  const selectedProfile: IdentityProfile | null = selectedEvent?.personId
    ? identityMemory?.profiles.find((profile) => profile.person_id === selectedEvent.personId) || null
    : null;

  useEffect(() => {
    const jobId = currentJob?.id;
    const personId = selectedEvent?.personId;
    if (!jobId || !personId) {
      setIdentityMemory(null);
      setIdentityError(null);
      return;
    }
    let cancelled = false;
    setIdentityLoading(true);
    setIdentityError(null);
    api.identities(jobId)
      .then((data) => {
        if (!cancelled) setIdentityMemory(data);
      })
      .catch((error: any) => {
        if (!cancelled) setIdentityError(error.message || "Identity evidence is not available yet");
      })
      .finally(() => {
        if (!cancelled) setIdentityLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentJob?.id, selectedEvent?.personId]);

  const handleStop = async () => {
    if (!currentJob) return;
    setStopping(true);
    setActionError(null);
    try {
      await api.stopJob(currentJob.id);
      onJobUpdated?.();
    } catch (e: any) {
      setActionError(e.message || "Failed to stop job");
    } finally {
      setStopping(false);
    }
  };

  const handleRetry = async () => {
    if (!currentJob) return;
    setRetrying(true);
    setActionError(null);
    try {
      const retry = await api.retryJob(currentJob.id);
      onSelectJobId?.(retry.id);
      onJobUpdated?.();
    } catch (e: any) {
      setActionError(e.message || "Failed to retry job");
    } finally {
      setRetrying(false);
    }
  };

  // Grounded telemetry from worker AI pipeline
  const hasTelemetry = Boolean(telemetry && telemetry.available);
  const isAmbiguous = hasTelemetry ? telemetry!.has_ambiguity : false;

  let faceState: "ABSENT" | "TENTATIVE" | "VISIBLE" | "COASTING" | "LOST" | "AWAITING" = "AWAITING";
  if (hasTelemetry) {
    if (telemetry!.tracks.length === 0) {
      faceState = "ABSENT";
    } else {
      const states = telemetry!.tracks.map((t) => t.face_state);
      if (states.includes("VISIBLE")) faceState = "VISIBLE";
      else if (states.includes("COASTING")) faceState = "COASTING";
      else if (states.includes("TENTATIVE")) faceState = "TENTATIVE";
      else if (states.includes("LOST")) faceState = "LOST";
      else faceState = "ABSENT";
    }
  }

  if (!currentJob) {
    return (
      <div className="panel" style={{ margin: "20px", height: "calc(100% - 40px)", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", color: "var(--text-muted)" }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ marginBottom: "12px", opacity: 0.5 }}>
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <h3>No Tracking Job Selected</h3>
          <p style={{ fontSize: "12px", marginTop: "4px" }}>Select a session from the top bar or launch a new job to start live monitoring.</p>
        </div>
      </div>
    );
  }

  const liveUrl = currentJob.media.live_url
    ? `${getAbsoluteUrl(currentJob.media.live_url)}?k=${refreshKey}`
    : null;
  const snapshotUrl = `${getAbsoluteUrl(currentJob.media.snapshot_url)}?k=${refreshKey}`;
  const playbackUrl = currentJob.media.playback_url ? getAbsoluteUrl(currentJob.media.playback_url) : null;
  const isCompletedReplay = currentJob.status === "COMPLETED" && Boolean(playbackUrl);

  return (
    <div className="live-container">
      {/* Player Viewport Pane */}
      <div className="live-player-pane">
        {/* Ambiguity Alert Banner */}
        {hasTelemetry ? (
          isAmbiguous ? (
            <div className="ambiguity-banner alert pulsing-alert">
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                  <line x1="12" y1="9" x2="12" y2="13"></line>
                  <line x1="12" y1="17" x2="12.01" y2="17"></line>
                </svg>
                <span>CROSSING AMBIGUITY (Frame #{telemetry?.frame}): IoU &ge; 0.50 · Body ReID learning paused.</span>
              </div>
              <span className="badge badge-crimson">PROTECTION ACTIVE</span>
            </div>
          ) : (
            <div className="ambiguity-banner">
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span className="badge-dot" style={{ background: "var(--color-emerald)" }}></span>
                <span>
                  {telemetry && telemetry.tracks_count > 0
                    ? `Frame #${telemetry.frame}: ${telemetry.tracks_count} track(s) active · Spatial bounding boxes clear of occlusion`
                    : `Frame #${telemetry?.frame ?? 0}: No persons in frame · Standing by`}
                </span>
              </div>
              <span className="badge badge-emerald">CONTINUITY NORMAL</span>
            </div>
          )
        ) : (
          <div className="ambiguity-banner" style={{ background: "rgba(100, 116, 139, 0.15)", borderColor: "var(--border-subtle)", color: "var(--text-muted)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span className="badge-dot" style={{ background: "var(--text-muted)" }}></span>
              <span>
                {isRunning ? "AWAITING TELEMETRY · Engine initializing stream and frame detector" : "SESSION ARCHIVED · Telemetry stored in final artifacts"}
              </span>
            </div>
            <span className="badge badge-muted">
              {isRunning ? "BUFFERING" : "STANDBY"}
            </span>
          </div>
        )}

        {/* Viewport Canvas */}
        <div className="live-viewport">
          {/* Top Overlays */}
          <div className="viewport-overlay-top">
            <div className="interactive-tag">
              <span className={`badge-dot ${isRunning ? "pulsing-live" : ""}`} style={{ background: isRunning ? "var(--color-cyan)" : "var(--text-muted)" }}></span>
                <span>{isCompletedReplay ? "SESSION REPLAY · " : "LIVE MONITOR · "}{currentJob.name}</span>
              <span style={{ color: "var(--text-muted)" }}>[{currentJob.source_kind}]</span>
            </div>

            {/* Face State Machine Ribbon */}
            <div className="face-ribbon interactive-tag">
              <span style={{ fontSize: "10px", color: "var(--text-dim)", textTransform: "uppercase" }}>Face State:</span>
              {hasTelemetry ? (
                <>
                  <span className={`state-chip ${faceState === "ABSENT" ? "active-lost" : ""}`}>ABSENT</span>
                  <span className={`state-chip ${faceState === "TENTATIVE" ? "active-coasting" : ""}`}>TENTATIVE</span>
                  <span className={`state-chip ${faceState === "VISIBLE" ? "active-visible" : ""}`}>VISIBLE</span>
                  <span className={`state-chip ${faceState === "COASTING" ? "active-coasting" : ""}`}>COASTING</span>
                  <span className={`state-chip ${faceState === "LOST" ? "active-lost" : ""}`}>LOST</span>
                </>
              ) : (
                <span className="state-chip" style={{ background: "rgba(100, 116, 139, 0.15)", color: "var(--text-muted)", borderColor: "var(--border-subtle)" }}>
                  {isRunning ? "AWAITING TELEMETRY" : currentJob.status}
                </span>
              )}
            </div>
          </div>

          {/* Live stream for active jobs; native forensic replay for completed jobs. */}
          {streamError && !isRunning ? (
            <div style={{ display: "grid", placeItems: "center", height: "100%", padding: "24px", color: "var(--text-muted)", textAlign: "center" }}>
              <div>
                <strong>No media available for this job</strong>
                <div style={{ fontSize: "11px", marginTop: "6px" }}>Job {currentJob.id} has no playable completed artifact or readable snapshot.</div>
              </div>
            </div>
          ) : isCompletedReplay ? (
            <video
              key={`replay-${currentJob.id}`}
              ref={videoRef}
              src={playbackUrl!}
              className="live-stream-img"
              controls
              preload="metadata"
              playsInline
            />
          ) : isRunning && liveUrl && !useSnapshotFallback ? (
            <img
              key={`live-${refreshKey}-${streamRetryCount}`}
              src={liveUrl}
              alt="Live annotated AI stream"
              className="live-stream-img"
             onLoad={() => { setStreamError(false); setUseSnapshotFallback(false); }}
             onError={() => { setStreamError(true); setUseSnapshotFallback(true); }}
            />
          ) : (
            <img
              key={`snap-${refreshKey}`}
              src={snapshotUrl}
              alt="Job frame snapshot"
              className="live-stream-img"
              onError={() => setStreamError(true)}
            />
          )}

          {/* Bottom Overlays */}
          <div className="viewport-overlay-bottom">
            <div className="interactive-tag">
              <span>Status: <b style={{ color: isRunning ? "var(--color-cyan)" : "var(--text-secondary)" }}>{currentJob.status}</b></span>
              <span>·</span>
              <span>{currentJob.progress.rows} track rows</span>
              <span>·</span>
              <span>{currentJob.progress.frames} live frames</span>
            </div>

            <div className="interactive-tag" style={{ gap: "10px" }}>
              {isCompletedReplay && (
                <label className="interactive-tag" style={{ fontSize: "11px" }}>
                  Speed
                  <select value={playbackRate} onChange={(event) => setPlaybackRate(Number(event.target.value))}>
                    <option value={0.5}>0.5x</option>
                    <option value={1}>1x</option>
                    <option value={1.5}>1.5x</option>
                    <option value={2}>2x</option>
                  </select>
                </label>
              )}
              <button
                className="btn btn-secondary"
                style={{ padding: "4px 8px", fontSize: "11px" }}
                 onClick={() => {
                   setStreamError(false);
                   setUseSnapshotFallback(false);
                   setStreamRetryCount((count) => count + 1);
                  setRefreshKey((k) => k + 1);
                }}
                title="Refresh image stream"
              >
                ↻ Refresh Stream
              </button>

              {isRunning ? (
                <button
                  className="btn btn-danger"
                  style={{ padding: "4px 8px", fontSize: "11px" }}
                  onClick={handleStop}
                  disabled={stopping}
                >
                  {stopping ? "Terminating…" : "■ Stop Process"}
                </button>
              ) : (
                <button
                  className="btn btn-secondary"
                  style={{ padding: "4px 8px", fontSize: "11px" }}
                  onClick={handleRetry}
                  disabled={retrying}
                >
                  {retrying ? "Launching…" : "↻ Retry Run"}
                </button>
              )}
            </div>
          </div>
        </div>

        {actionError && (
          <div style={{ padding: "8px 12px", background: "var(--color-crimson-glow)", border: "1px solid var(--color-crimson-border)", color: "var(--color-crimson)", borderRadius: "var(--radius-sm)", fontSize: "11px" }}>
            Action error: {actionError}
          </div>
        )}
      </div>

      {/* Live Ticker Side Pane */}
      <div className="panel live-ticker-pane">
        <div className="panel-header">
          <span className="panel-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
            </svg>
            Biometric Event Ticker
          </span>
          <span className="badge badge-cyan">{summary?.identities.length ?? 0} PROFILES</span>
        </div>

        <div className="ticker-list">
          {selectedEvent && (
            <div className="ticker-detail">
              <div className="ticker-detail-header">
                <div>
                  <div className="panel-title">Person Evidence</div>
                  <div className="ticker-detail-id">{selectedEvent.personId || `TRACK-${selectedEvent.trackId}`}</div>
                </div>
                <button className="btn btn-secondary ticker-close" onClick={() => setSelectedEventKey(null)}>Close</button>
              </div>

              <div className="evidence-stats">
                <span>Track #{selectedEvent.trackId}</span>
                <span>Frame #{selectedEvent.frame}</span>
                <span>Face: {selectedEvent.faceState}</span>
                <span>State: {selectedEvent.identityState}</span>
                {selectedEvent.ambiguous && <span className="evidence-warning">AMBIGUOUS</span>}
              </div>

              {identityLoading && <div className="ticker-meta">Loading face/body evidence…</div>}
              {identityError && <div className="ticker-meta evidence-warning">{identityError}</div>}
              {selectedEvent.personId && selectedProfile && (
                <>
                  <div className="profile-facts">
                    <span>Employee: <b>{selectedProfile.employee_id || "UNNAMED"}</b></span>
                    <span>Maturity: <b>{selectedProfile.maturity}</b></span>
                    <span>Confidence: <b>{Number(selectedProfile.confidence || 0).toFixed(3)}</b></span>
                    <span>Face anchors: <b>{selectedProfile.face_anchor_count}</b></span>
                    <span>Face obs: <b>{selectedProfile.face_observations}</b></span>
                    <span>Body obs: <b>{selectedProfile.body_observations}</b></span>
                    <span>Conflicts: <b>{selectedProfile.conflict_count}</b></span>
                    <span>Members: <b>{selectedProfile.members.length}</b></span>
                  </div>
                  <EvidenceCrops title="Face crops by pose" samples={selectedProfile.face_memory} />
                  <EvidenceCrops title="Body/ReID evidence" samples={selectedProfile.body_memory} />
                </>
              )}
              {selectedEvent.personId && !identityLoading && !selectedProfile && !identityError && (
                <div className="ticker-meta">Person ID is active, but the persistent profile/crops have not been finalized yet.</div>
              )}
              {!selectedEvent.personId && (
                <div className="ticker-meta">No persistent person ID yet. Face evidence is still tentative or not sufficient for binding.</div>
              )}
            </div>
          )}

          {isRunning && telemetry?.tracks && telemetry.tracks.length > 0 && (
            <div className="ticker-item" style={{ borderColor: "var(--color-cyan)" }}>
              <div className="ticker-header">
                <span className="ticker-badge badge-cyan">LIVE FACE / IDENTITY</span>
                <span className="ticker-time">Frame #{telemetry.frame}</span>
              </div>
              {telemetry.tracks.map((track) => (
                <button
                  key={track.track_id}
                  className="ticker-person-row"
                  onClick={() => setSelectedEventKey(`${currentJob?.id}-${track.track_id}-${telemetry.frame}`)}
                >
                  <span>Track #{track.track_id} · <b>{track.person_id || `TRACK-${track.track_id}`}</b></span>
                  <span>
                    {track.face_state} · {track.identity_state || "UNIDENTIFIED"}
                    {track.face_decision ? ` · ${track.face_decision}` : ""}
                    {track.face_candidate_needed ? ` ${track.face_candidate_votes || 0}/${track.face_candidate_needed}` : ""}
                    {track.ambiguous ? " · AMBIGUITY" : ""}
                  </span>
                </button>
              ))}
            </div>
          )}
          {liveEvents.length > 0 && (
            <div className="ticker-history-block">
              <div className="ticker-section-label">Realtime person history</div>
              {liveEvents.slice(0, 16).map((event) => (
                <button
                  key={event.key}
                  className={`ticker-item ticker-clickable ${selectedEventKey === event.key ? "selected" : ""}`}
                  onClick={() => setSelectedEventKey(event.key)}
                >
                  <div className="ticker-header">
                    <span className={`ticker-badge ${event.personId ? "badge-emerald" : "badge-amber"}`}>
                      {event.personId || `TRACK-${event.trackId}`}
                    </span>
                    <span className="ticker-time">Frame #{event.frame}</span>
                  </div>
                  <div className="ticker-body">Face: <b>{event.faceState}</b> · State: <b>{event.identityState}</b></div>
                  <div className="ticker-meta">Track #{event.trackId}{event.ambiguous ? " · Body learning paused" : " · Evidence accepted"}</div>
                </button>
              ))}
            </div>
          )}
          {summary?.recent_events && summary.recent_events.length > 0 ? (
            summary.recent_events
              .slice()
              .reverse()
              .map((evt, idx) => (
                <div key={idx} className="ticker-item">
                  <div className="ticker-header">
                    <span className="ticker-badge badge-emerald">
                      {String(evt.event || "IDENTITY_EVENT")}
                    </span>
                    <span className="ticker-time">Frame #{evt.frame}</span>
                  </div>
                  <div className="ticker-body">
                    {evt.new_identity_id ? (
                      <span>Identity bound: <b>{String(evt.new_identity_id)}</b></span>
                    ) : (
                      <span>Tracklet update: #{String(evt.tracklet_id ?? "—")}</span>
                    )}
                  </div>
                  {evt.evidence_json && (
                    <div className="ticker-meta">
                      Evidence: {typeof evt.evidence_json === "string" ? evt.evidence_json : JSON.stringify(evt.evidence_json)}
                    </div>
                  )}
                </div>
              ))
          ) : recentTracks.length > 0 ? (
            recentTracks
              .slice(-15)
              .reverse()
              .map((tr, idx) => (
                <div key={idx} className="ticker-item">
                  <div className="ticker-header">
                    <span className={`ticker-badge ${tr.identity_state === "CONFIRMED" ? "badge-emerald" : tr.identity_state === "CONFLICT" ? "badge-crimson" : "badge-amber"}`}>
                      {tr.identity_state || tr.fusion_state || "TRACK"}
                    </span>
                    <span className="ticker-time">Frame #{tr.frame}</span>
                  </div>
                  <div className="ticker-body">
                    Track #{tr.track_id} &rarr; <b>{tr.person_id || tr.identity || "UNBOUND"}</b>
                  </div>
                  <div className="ticker-meta">
                    Face: {tr.face_state} ({Number(tr.face_score || 0).toFixed(2)}) · Pose: {tr.face_id_pose || "—"} · Fusion: {tr.fusion_reason || "NOMINAL"}
                  </div>
                </div>
              ))
          ) : (
            <div style={{ textAlign: "center", padding: "30px 10px", color: "var(--text-muted)", fontSize: "12px" }}>
              No detection events recorded yet for this session.
            </div>
          )}
          {!isRunning && summary?.recent_events && summary.recent_events.length > 0 && recentTracks.length > 0 && (
            <div className="ticker-item" style={{ borderColor: "var(--color-violet)" }}>
              <div className="ticker-header">
                <span className="ticker-badge" style={{ background: "rgba(139,92,246,.18)", color: "#c4b5fd" }}>FACE / IDENTITY EVIDENCE</span>
                <span className="ticker-time">Selected job</span>
              </div>
              {recentTracks.slice(-8).reverse().map((track, idx) => (
                <div key={`${track.track_id}-${track.frame}-${idx}`} className="ticker-meta" style={{ marginTop: "6px" }}>
                  Frame #{track.frame} · Track #{track.track_id} · Face: {track.face_state || "—"} · Face ID: {track.face_id_person || track.face_id_top1 || "UNKNOWN"} · Person: {track.person_id || "UNBOUND"} · Identity: {track.identity_state || track.fusion_state || "UNIDENTIFIED"}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

function EvidenceCrops({ title, samples }: { title: string; samples: IdentityProfile["face_memory"] }) {
  if (!samples.length) return null;
  return (
    <div className="evidence-crops">
      <div className="ticker-section-label">{title}</div>
      <div className="crop-grid">
        {samples.slice(0, 9).map((sample, index) => (
          <div className="crop-card" key={`${sample.image_url}-${index}`}>
            <img src={getAbsoluteUrl(sample.image_url)} alt={`${sample.pose || "evidence"} crop`} />
            <div className="crop-label">{sample.pose || "view"}</div>
            <div className="crop-meta">Q {Number(sample.quality || 0).toFixed(2)} · {sample.tier || "sample"}</div>
            {sample.first_frame !== undefined && <div className="crop-meta">F {sample.first_frame}–{sample.last_frame ?? sample.first_frame}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
