import React, { useState, useEffect, useMemo, useRef } from "react";
import { Job, api, API, getAbsoluteUrl, formatBytes, formatTimestamp, formatDuration } from "../../api";
import "./archive.css";

interface ArchiveViewProps {
  jobs: Job[];
  selectedJobId: string | null;
  onSelectJobId: (id: string) => void;
  onJobUpdated?: () => void;
}

export const ArchiveView: React.FC<ArchiveViewProps> = ({
  jobs,
  selectedJobId,
  onSelectJobId,
  onJobUpdated,
}) => {
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [logText, setLogText] = useState<string>("");
  const [logLoading, setLogLoading] = useState<boolean>(false);
  const [logError, setLogError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const terminalRef = useRef<HTMLDivElement>(null);

  const activeJob = useMemo(() => {
    return selectedJobId ? jobs.find((j) => j.id === selectedJobId) ?? null : null;
  }, [jobs, selectedJobId]);

  const filteredJobs = useMemo(() => {
    return jobs.filter((j) => {
      const matchStatus = statusFilter === "ALL" || j.status === statusFilter;
      const matchQuery =
        !searchQuery.trim() ||
        j.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        j.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        j.source_kind.toLowerCase().includes(searchQuery.toLowerCase());
      return matchStatus && matchQuery;
    });
  }, [jobs, statusFilter, searchQuery]);

  // Fetch log whenever activeJob changes
  useEffect(() => {
    if (!activeJob) {
      setLogText("");
      return;
    }

    let isMounted = true;
    setLogLoading(true);
    setLogError(null);

    api
      .log(activeJob.id, 500)
      .then((txt) => {
        if (!isMounted) return;
        setLogText(txt);
      })
      .catch((err) => {
        if (!isMounted) return;
        setLogError(err.message || "Log not ready or missing");
        setLogText("");
      })
      .finally(() => {
        if (isMounted) setLogLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [activeJob?.id, activeJob?.status]);

  const handleCopyLog = () => {
    if (!logText) return;
    navigator.clipboard.writeText(logText);
    setActionMsg("Log copied to clipboard!");
    setTimeout(() => setActionMsg(null), 2500);
  };

  const handleRetry = async () => {
    if (!activeJob) return;
    try {
      const retry = await api.retryJob(activeJob.id);
      onSelectJobId(retry.id);
      setActionMsg("Retry job launched successfully.");
      onJobUpdated?.();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (e: any) {
      setActionMsg(`Retry failed: ${e.message}`);
    }
  };

  const handleStop = async () => {
    if (!activeJob) return;
    try {
      await api.stopJob(activeJob.id);
      setActionMsg("Stop signal dispatched.");
      onJobUpdated?.();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (e: any) {
      setActionMsg(`Stop failed: ${e.message}`);
    }
  };

  const statusTone = (status: string) => {
    switch (status) {
      case "COMPLETED":
        return "badge-emerald";
      case "RUNNING":
      case "CANCEL_REQUESTED":
        return "badge-cyan pulsing-live";
      case "FAILED":
        return "badge-crimson";
      case "STOPPED":
        return "badge-amber";
      default:
        return "badge-muted";
    }
  };

  return (
    <div className="archive-container">
      {/* Sidebar: Jobs Ledger */}
      <div className="panel archive-sidebar">
        <div className="filter-bar">
          <input
            type="text"
            placeholder="Filter sessions by name / ID…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />

          <div className="status-tabs">
            {["ALL", "COMPLETED", "RUNNING", "FAILED", "STOPPED"].map((s) => (
              <button
                key={s}
                className={`status-tab ${statusFilter === s ? "active" : ""}`}
                onClick={() => setStatusFilter(s)}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <div className="jobs-ledger">
          {filteredJobs.map((job) => {
            const isSelected = activeJob?.id === job.id;
            const duration = job.started_at && job.finished_at ? job.finished_at - job.started_at : null;

            return (
              <div
                key={job.id}
                className={`job-card ${isSelected ? "active" : ""}`}
                onClick={() => onSelectJobId(job.id)}
              >
                <div className="job-header">
                  <span className="job-name" title={job.name}>{job.name}</span>
                  <span className={`badge ${statusTone(job.status)}`}>{job.status}</span>
                </div>

                <div className="job-meta-row">
                  <span>ID: <code>{job.id.slice(0, 8)}</code></span>
                  <span>[{job.source_kind}]</span>
                  <span>{job.progress.rows} rows</span>
                </div>

                <div className="job-meta-row" style={{ color: "var(--text-dim)" }}>
                  <span>{formatTimestamp(job.created_at)}</span>
                  <span>{formatDuration(duration)}</span>
                </div>
              </div>
            );
          })}

          {filteredJobs.length === 0 && (
            <div style={{ textAlign: "center", padding: "30px 10px", color: "var(--text-dim)", fontSize: "12px" }}>
              No sessions match the selected filter.
            </div>
          )}
        </div>
      </div>

      {/* Main Detail & Log Inspector */}
      {activeJob ? (
        <div className="panel archive-detail-pane">
          {/* Detail Banner */}
          <div className="detail-banner">
            <div className="detail-banner-info">
              <div className="detail-title">
                <span>{activeJob.name}</span>
                <span className={`badge ${statusTone(activeJob.status)}`}>{activeJob.status}</span>
                <span className="badge badge-muted">KIND: {activeJob.source_kind}</span>
              </div>
              <div style={{ fontSize: "11px", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                Job ID: <code>{activeJob.id}</code> · Source: <code>{activeJob.source}</code> · Started: {formatTimestamp(activeJob.started_at)}
              </div>
              {activeJob.error && (
                <div style={{ fontSize: "11px", color: "var(--color-crimson)", marginTop: "4px" }}>
                  Error Trace: {activeJob.error}
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: "8px" }}>
              {activeJob.status === "RUNNING" ? (
                <button className="btn btn-danger" onClick={handleStop}>
                  ■ Stop Execution
                </button>
              ) : (
                <button className="btn btn-secondary" onClick={handleRetry}>
                  ↻ Retry Session
                </button>
              )}
            </div>
          </div>

          {actionMsg && (
            <div style={{ padding: "8px 12px", background: "var(--color-cyan-glow)", border: "1px solid var(--color-cyan-border)", color: "var(--color-cyan)", borderRadius: "var(--radius-sm)", fontSize: "11px" }}>
              {actionMsg}
            </div>
          )}

          {/* Artifacts Explorer Grid */}
          <div className="panel" style={{ padding: "16px", gap: "12px" }}>
            <div className="panel-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              Forensic Evidence & Artifacts Manifest ({activeJob.artifacts.length} files)
            </div>

            <div className="artifacts-grid">
              {activeJob.artifacts.map((art, idx) => {
                const downloadUrl = `/api/jobs/${activeJob.id}/artifacts/${art.name}`;

                return (
                  <div key={idx} className="artifact-card">
                    <div className="artifact-left">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: "var(--color-cyan)", flexShrink: 0 }}>
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                      </svg>
                      <div className="artifact-file-info">
                        <span className="artifact-filename" title={art.name}>{art.name}</span>
                        <span className="artifact-filesize">{formatBytes(art.size)} · {art.state}</span>
                      </div>
                    </div>

                    <a
                      href={getAbsoluteUrl(downloadUrl)}
                      download={art.name}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-secondary"
                      style={{ padding: "3px 8px", fontSize: "11px" }}
                      title="Download artifact directly"
                    >
                      ↓ Save
                    </a>
                  </div>
                );
              })}

              {activeJob.artifacts.length === 0 && (
                <div style={{ gridColumn: "span 3", color: "var(--text-dim)", fontSize: "11px", padding: "10px 0" }}>
                  No output artifacts exported yet.
                </div>
              )}
            </div>
          </div>

          {/* Terminal Console Log */}
          <div className="log-terminal">
            <div className="terminal-header">
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span className="badge-dot" style={{ background: activeJob.status === "RUNNING" ? "var(--color-cyan)" : "var(--text-muted)" }}></span>
                <span>Console Log: <code>output/logs/worker.log</code> (Last 500 lines)</span>
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <a
                  href={`${API}/jobs/${activeJob.id}/log?full=true`}
                  download={`${activeJob.id}_worker.log`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-secondary"
                  style={{ padding: "2px 8px", fontSize: "10px" }}
                >
                  ↓ Full Log
                </a>
                <button className="btn btn-secondary" style={{ padding: "2px 8px", fontSize: "10px" }} onClick={handleCopyLog}>
                  Copy
                </button>
              </div>
            </div>

            <div className="terminal-body" ref={terminalRef}>
              {logLoading ? (
                <span style={{ color: "var(--text-muted)" }}>Streaming worker stdout/stderr…</span>
              ) : logError ? (
                <span style={{ color: "var(--text-dim)" }}>{logError}</span>
              ) : logText ? (
                logText
              ) : (
                <span style={{ color: "var(--text-dim)" }}>No stdout/stderr logged for this run.</span>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="panel archive-detail-pane" style={{ alignItems: "center", justifyContent: "center" }}>
          <div style={{ textAlign: "center", color: "var(--text-muted)" }}>
            <h3>Select a Forensic Session</h3>
            <p style={{ fontSize: "12px", marginTop: "4px" }}>Choose an execution job from the left ledger to inspect its artifacts and worker logs.</p>
          </div>
        </div>
      )}
    </div>
  );
};
