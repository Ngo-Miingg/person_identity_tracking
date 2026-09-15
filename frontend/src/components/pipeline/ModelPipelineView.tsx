import React, { useState, useEffect } from "react";
import { Job, api, JobDetails } from "../../api";
import "./pipeline.css";

interface ModelPipelineViewProps {
  selectedJob: Job | null;
}

export const ModelPipelineView: React.FC<ModelPipelineViewProps> = ({ selectedJob }) => {
  const [details, setDetails] = useState<JobDetails | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const jobId = selectedJob?.id ?? null;

  useEffect(() => {
    if (!jobId) {
      setDetails(null);
      setLoading(false);
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError(null);

    api
      .details(jobId)
      .then((data) => {
        if (!isMounted) return;
        setDetails(data);
      })
      .catch((err) => {
        if (!isMounted) return;
        setError(err.message || "Failed to load session details");
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [jobId]);

  if (!selectedJob) {
    return (
      <div className="panel" style={{ margin: "20px", height: "calc(100% - 40px)", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", color: "var(--text-muted)" }}>
          <h3>No Session Selected</h3>
          <p style={{ fontSize: "12px", marginTop: "4px" }}>Select a session from the top bar to inspect model pipeline telemetry.</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="panel" style={{ margin: "20px", height: "calc(100% - 40px)", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", color: "var(--text-muted)" }}>
          <span className="badge-dot pulsing-live" style={{ background: "var(--color-cyan)", marginBottom: "8px" }} />
          <h3>Loading Pipeline Architecture & SQLite Store…</h3>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel" style={{ margin: "20px", height: "calc(100% - 40px)", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", color: "var(--color-crimson)" }}>
          <h3>Failed to Load Pipeline Details</h3>
          <p style={{ fontSize: "12px", marginTop: "4px" }}>{error}</p>
        </div>
      </div>
    );
  }

  const tables = details?.database.tables || {};
  const ledgerRows = details?.tracks.length ? details.tracks : (details?.tracklets || []);

  return (
    <div className="pipeline-container">
      {/* Visual Multi-Model Architecture Flow */}
      <div className="architecture-card">
        <div className="panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
          </svg>
          Multi-Modal Identity Inference Architecture (5 Models in Cascade)
        </div>

        <div className="pipeline-flow">
          {/* Stage 1: Detector & Tracker */}
          <div className="flow-stage">
            <div className="flow-header">
              <span className="flow-title">1. Detection & Track</span>
              <span className="badge badge-cyan">YOLO + BoT</span>
            </div>
            <div className="flow-body">
              <div className="flow-chip">YOLO11s (COCO person, class 0)</div>
              <div className="flow-chip">BoT-SORT tracker (buffer=60)</div>
              <div className="flow-chip">Local Track ID assignment</div>
              <div className="flow-chip">Spatial coordinates [x1, y1, x2, y2]</div>
            </div>
          </div>

          {/* Stage 2: Face Recognition Channel */}
          <div className="flow-stage highlight-face">
            <div className="flow-header">
              <span className="flow-title">2. Face Authority</span>
              <span className="badge badge-cyan">SCRFD + AdaFace</span>
            </div>
            <div className="flow-body">
              <div className="flow-chip">Head ROI extraction (+30% exp)</div>
              <div className="flow-chip">SCRFD 10G ONNX (5 landmarks)</div>
              <div className="flow-chip">Temporal Tracker (Visible/Coasting)</div>
              <div className="flow-chip">AdaFace IR50 (512-D + Feature Norm)</div>
            </div>
          </div>

          {/* Stage 3: Body ReID Channel */}
          <div className="flow-stage highlight-body">
            <div className="flow-header">
              <span className="flow-title">3. Body Continuity</span>
              <span className="badge badge-violet">OSNet x1.0</span>
            </div>
            <div className="flow-body">
              <div className="flow-chip">Crossing filter (IoU &ge; 0.50 pause)</div>
              <div className="flow-chip">OSNet x1.0 MSMT17 (512-D)</div>
              <div className="flow-chip">Appearance reservoir (128 vectors)</div>
              <div className="flow-chip">Gap continuity & reacquisition</div>
            </div>
          </div>

          {/* Stage 4: Evidence Fusion */}
          <div className="flow-stage highlight-fusion">
            <div className="flow-header">
              <span className="flow-title">4. Evidence Fusion</span>
              <span className="badge badge-emerald">Decision Engine</span>
            </div>
            <div className="flow-body">
              <div className="flow-chip">Rule: Face is sole authority</div>
              <div className="flow-chip">Rule: Body never overwrites ID</div>
              <div className="flow-chip">Margin check (&ge; 0.07 required)</div>
              <div className="flow-chip">States: CONFIRMED / PROVISIONAL</div>
            </div>
          </div>

          {/* Stage 5: Database Persistence */}
          <div className="flow-stage">
            <div className="flow-header">
              <span className="flow-title">5. SQLite Source</span>
              <span className="badge badge-emerald">PRAGMA OK</span>
            </div>
            <div className="flow-body">
              <div className="flow-chip">Atomic WAL mode transactions</div>
              <div className="flow-chip">Canonical promotion engine</div>
              <div className="flow-chip">NPZ vector archive (Face/Body)</div>
              <div className="flow-chip">Artifacts manifest exporter</div>
            </div>
          </div>
        </div>
      </div>

      {/* Database Relational Store Telemetry */}
      <div className="architecture-card">
        <div className="panel-title" style={{ justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
            </svg>
            SQLite Relational Store Telemetry (`identity.sqlite`)
          </div>
          <span className="badge badge-emerald">INTEGRITY: {details?.database.integrity ?? "OK"}</span>
        </div>

        <div className="db-grid">
          <div className="db-card">
            <span className="db-title">Tracklets</span>
            <span className="db-value">{tables.tracklets ?? 0}</span>
          </div>
          <div className="db-card">
            <span className="db-title">Detections (YOLO)</span>
            <span className="db-value">{tables.detections ?? 0}</span>
          </div>
          <div className="db-card">
            <span className="db-title">Observations (Vectors)</span>
            <span className="db-value">{tables.observations ?? 0}</span>
          </div>
          <div className="db-card">
            <span className="db-title">Identity Assignments</span>
            <span className="db-value">{tables.assignments ?? 0}</span>
          </div>
          <div className="db-card">
            <span className="db-title">Fusion Decisions</span>
            <span className="db-value">{tables.fusion_decisions ?? 0}</span>
          </div>
          <div className="db-card">
            <span className="db-title">SQLite Identity Events</span>
            <span className="db-value">{tables.identity_events ?? 0}</span>
          </div>
          <div className="db-card">
            <span className="db-title">Artifact Identity Events</span>
            <span className="db-value">{details?.events.length ?? 0}</span>
          </div>
        </div>
      </div>

      {/* Tracklet Resolution Ledger Table */}
      <div className="tracks-table-card">
        <div className="panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="8" y1="6" x2="21" y2="6"></line>
            <line x1="8" y1="12" x2="21" y2="12"></line>
            <line x1="8" y1="18" x2="21" y2="18"></line>
            <line x1="3" y1="6" x2="3.01" y2="6"></line>
            <line x1="3" y1="12" x2="3.01" y2="12"></line>
            <line x1="3" y1="18" x2="3.01" y2="18"></line>
          </svg>
          Tracklet Resolution Ledger ({tables.tracklets ?? ledgerRows.length} tracklets recorded)
        </div>

        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Camera</th>
                <th>Track ID</th>
                <th>Bound Person ID</th>
                <th>Final State</th>
                <th>Bind Reason</th>
                <th>Frame Span</th>
                <th>Face Obs</th>
                <th>Body Obs</th>
                <th>Ambiguity Frames</th>
                <th>Conflict</th>
              </tr>
            </thead>
            <tbody>
              {ledgerRows.length > 0 ? (
                ledgerRows.map((t, idx) => (
                  <tr key={idx}>
                    <td><code>{t.camera}</code></td>
                    <td><code>#{t.track_id}</code></td>
                    <td>
                      <b style={{ color: "var(--color-cyan)" }}>
                        {t.person_id || "UNBOUND"}
                      </b>
                      {t.confirmed_employee && (
                        <span className="badge badge-emerald" style={{ marginLeft: "6px" }}>
                          {t.confirmed_employee}
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${t.final_state === "CONFIRMED" ? "badge-emerald" : t.final_state === "CONFLICT" ? "badge-crimson" : "badge-amber"}`}>
                        {t.final_state}
                      </span>
                    </td>
                    <td><span style={{ fontSize: "11px", color: "var(--text-muted)" }}>{t.bind_reason}</span></td>
                    <td><code>{t.first_frame} – {t.last_frame}</code></td>
                    <td>{t.online_face_observations ?? t.face_observations ?? 0}</td>
                    <td>{t.online_body_observations ?? t.body_observations ?? 0}</td>
                    <td>
                      {t.ambiguous_frames > 0 ? (
                        <span style={{ color: "var(--color-amber)", fontWeight: 600 }}>{t.ambiguous_frames} frames</span>
                      ) : (
                        <span style={{ color: "var(--text-dim)" }}>0</span>
                      )}
                    </td>
                    <td>
                      {t.strong_face_conflict ? (
                        <span className="badge badge-crimson">ALERT</span>
                      ) : (
                        <span className="badge badge-emerald">NONE</span>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={10} style={{ textAlign: "center", padding: "30px", color: "var(--text-dim)" }}>
                    No tracklets recorded in this session.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
