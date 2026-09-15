import React from "react";

export type NavView = "live" | "identities" | "pipeline" | "archive" | "sources";

interface SidebarProps {
  currentView: NavView;
  onNavigate: (view: NavView) => void;
  isRunning: boolean;
  profileCount: number;
  jobCount: number;
  sourceCount: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onNavigate,
  isRunning,
  profileCount,
  jobCount,
  sourceCount,
}) => {
  return (
    <aside className="app-sidebar">
      <div className="nav-group">
        <div className="nav-label">Operations</div>

        <button
          className={`nav-btn ${currentView === "live" ? "active" : ""}`}
          onClick={() => onNavigate("live")}
        >
          <div className="nav-btn-left">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="23 7 16 12 23 17 23 7"></polygon>
              <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
            </svg>
            <span>Live Monitor</span>
          </div>
          {isRunning && <span className="badge-dot pulsing-live" style={{ background: "var(--color-cyan)" }} />}
        </button>

        <button
          className={`nav-btn ${currentView === "identities" ? "active" : ""}`}
          onClick={() => onNavigate("identities")}
        >
          <div className="nav-btn-left">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
              <circle cx="12" cy="7" r="4"></circle>
            </svg>
            <span>Identity Hub</span>
          </div>
          {profileCount > 0 && <span className="nav-counter">{profileCount}</span>}
        </button>

        <button
          className={`nav-btn ${currentView === "pipeline" ? "active" : ""}`}
          onClick={() => onNavigate("pipeline")}
        >
          <div className="nav-btn-left">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
            </svg>
            <span>Model Pipeline</span>
          </div>
        </button>

        <div className="nav-label" style={{ marginTop: "14px" }}>Management</div>

        <button
          className={`nav-btn ${currentView === "archive" ? "active" : ""}`}
          onClick={() => onNavigate("archive")}
        >
          <div className="nav-btn-left">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
              <polyline points="10 9 9 9 8 9"></polyline>
            </svg>
            <span>Forensic Archive</span>
          </div>
          {jobCount > 0 && <span className="nav-counter">{jobCount}</span>}
        </button>

        <button
          className={`nav-btn ${currentView === "sources" ? "active" : ""}`}
          onClick={() => onNavigate("sources")}
        >
          <div className="nav-btn-left">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="2" y1="12" x2="22" y2="12"></line>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
            </svg>
            <span>Source Fleet</span>
          </div>
          {sourceCount > 0 && <span className="nav-counter">{sourceCount}</span>}
        </button>
      </div>

      <div className="sidebar-footer" style={{ padding: "8px", borderTop: "1px solid var(--border-subtle)", fontSize: "11px", color: "var(--text-dim)" }}>
        <div>Pipeline: <b>5 Models Active</b></div>
        <div style={{ marginTop: "4px" }}>YOLO11s · SCRFD · AdaFace · OSNet · Fusion</div>
      </div>
    </aside>
  );
};
