import React from "react";
import { Job } from "../../api";

interface HeaderProps {
  apiConnected: boolean;
  activeJob: Job | null;
  selectedJob: Job | null;
  jobs: Job[];
  onSelectJobId: (id: string) => void;
  onOpenNewJobModal: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  apiConnected,
  activeJob,
  selectedJob,
  jobs,
  onSelectJobId,
  onOpenNewJobModal,
}) => {
  return (
    <header className="app-header">
      <div className="header-brand">
        <div className="brand-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18" />
          </svg>
        </div>
        <div className="brand-text">
          <div className="brand-title">Identity Tracker Ops</div>
          <div className="brand-subtitle">v2.1.0-face-anchor-authority</div>
        </div>
      </div>

      <div className="header-telemetry">
        {/* Backend Connectivity */}
        <div className="telemetry-item">
          <span className="telemetry-label">API:</span>
          {apiConnected ? (
            <span className="badge badge-emerald">ONLINE</span>
          ) : (
            <span className="badge badge-crimson">DISCONNECTED</span>
          )}
        </div>

        {/* Global Inference Execution Lock */}
        <div className="telemetry-item">
          <span className="telemetry-label">Inference Lock:</span>
          {activeJob ? (
            <span className="badge badge-amber pulsing-live" title={`Running: ${activeJob.name}`}>
              LOCKED ({activeJob.id.slice(0, 6)})
            </span>
          ) : (
            <span className="badge badge-emerald">IDLE AVAILABLE</span>
          )}
        </div>

        {/* Selected Job / Session Selector */}
        <div className="session-selector-wrap">
          <span className="telemetry-label">Session:</span>
          <select
            className="session-select"
            value={selectedJob?.id ?? ""}
            onChange={(e) => onSelectJobId(e.target.value)}
          >
            {jobs.length === 0 ? (
              <option value="">No sessions available</option>
            ) : (
              jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  [{j.status}] {j.name || j.id} ({j.source_kind})
                </option>
              ))
            )}
          </select>
        </div>

        {/* Quick Launch Job */}
        <button
          className="btn btn-primary"
          onClick={onOpenNewJobModal}
          disabled={activeJob !== null}
          title={activeJob ? "Global execution lock is currently held by a running job" : "Start a new tracking job"}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          Launch Job
        </button>
      </div>
    </header>
  );
};
