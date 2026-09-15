import React from "react";
import { Job } from "../../api";

interface FooterProps {
  activeJob: Job | null;
  selectedJob: Job | null;
}

export const Footer: React.FC<FooterProps> = ({ activeJob, selectedJob }) => {
  const current = activeJob || selectedJob;

  return (
    <footer className="app-footer">
      <div className="footer-left">
        <span className="footer-indicator">
          <span
            className="indicator-dot"
            style={{
              background: activeJob ? "var(--color-amber)" : "var(--color-emerald)",
            }}
          />
          {activeJob ? `INFERENCE ACTIVE: ${activeJob.name} (${activeJob.id})` : "INFERENCE ENGINE STANDBY"}
        </span>

        {current && (
          <span>
            JOB: <b>{current.id}</b> · ROWS: <b>{current.progress.rows}</b> ({current.progress.frames} live frames) · PHASE: <b>{current.progress.phase.toUpperCase()}</b>
            {current.pid ? ` · PID: #${current.pid}` : ""}
          </span>
        )}
      </div>

      <div className="footer-right">
        {current ? (
          <>
            <span>SOURCE: {current.source_kind.toUpperCase()}</span>
            <span>ARTIFACTS: {current.artifacts.length}</span>
            <span>MEDIA: {current.media.state}</span>
          </>
        ) : (
          <>
            <span>HOST PLATFORM: Windows x64</span>
            <span>PIPELINE: YOLO11s · SCRFD · AdaFace · OSNet</span>
          </>
        )}
      </div>
    </footer>
  );
};
