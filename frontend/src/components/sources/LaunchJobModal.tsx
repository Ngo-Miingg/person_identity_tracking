import React, { useEffect, useState } from "react";
import { Source, api } from "../../api";

interface LaunchJobModalProps {
  sources: Source[];
  initialSourceId?: string | null;
  isOpen: boolean;
  onClose: () => void;
  onJobStarted: (jobId: string) => void;
  isLocked: boolean;
}

export const LaunchJobModal: React.FC<LaunchJobModalProps> = ({
  sources,
  initialSourceId,
  isOpen,
  onClose,
  onJobStarted,
  isLocked,
}) => {
  const [selectedSourceId, setSelectedSourceId] = useState<string>("");
  const [jobName, setJobName] = useState<string>("Identity Tracking Job");
  const device = "0";
  const [useGallery, setUseGallery] = useState<boolean>(true);
  const [galleryPath, setGalleryPath] = useState<string>("gallery");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && initialSourceId && sources.some((source) => source.id === initialSourceId)) {
      setSelectedSourceId(initialSourceId);
      return;
    }
    if (sources.length > 0 && !sources.some((source) => source.id === selectedSourceId)) {
      const defaultSource = sources.find(
        (source) => source.kind === "rtsp" && source.uri.includes("172.16.16.27") && source.uri.includes("/Streaming/Channels/101"),
      ) || sources[0];
      setSelectedSourceId(defaultSource.id);
    }
  }, [initialSourceId, isOpen, sources, selectedSourceId]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLocked) {
      setError("Cannot launch job: another inference process is currently running.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const job = await api.createJob({
        source_id: selectedSourceId || undefined,
        name: jobName.trim() || "Identity Tracking Job",
        device: device,
        gallery: useGallery && galleryPath.trim() ? galleryPath.trim() : null,
      });

      onJobStarted(job.id);
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to start tracking job");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="panel-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            Launch Identity Tracking Job
          </span>
          <button className="btn btn-secondary" style={{ padding: "2px 6px" }} onClick={onClose}>
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {isLocked && (
              <div style={{ padding: "8px 12px", background: "var(--color-amber-glow)", border: "1px solid var(--color-amber-border)", color: "var(--color-amber)", borderRadius: "var(--radius-sm)", fontSize: "11px" }}>
                Global execution lock active. Wait for current job to complete or stop it first.
              </div>
            )}

            {error && (
              <div style={{ padding: "8px 12px", background: "var(--color-crimson-glow)", border: "1px solid var(--color-crimson-border)", color: "var(--color-crimson)", borderRadius: "var(--radius-sm)", fontSize: "11px" }}>
                {error}
              </div>
            )}

            <div className="form-group">
              <label className="form-label">Job Name</label>
              <input
                type="text"
                value={jobName}
                onChange={(e) => setJobName(e.target.value)}
                placeholder="Session identifier name"
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Input Source</label>
              <select
                value={selectedSourceId}
                onChange={(e) => setSelectedSourceId(e.target.value)}
                required
              >
                {sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.kind} — {s.uri || "default"})
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Inference GPU</label>
              <div
                style={{
                  padding: "8px 10px",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--text-primary)",
                  background: "var(--surface-raised)",
                  fontSize: "12px",
                }}
              >
                NVIDIA GeForce RTX 3050 · CUDA:0 · FP16
              </div>
              <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
                The console is locked to the installed RTX 3050 GPU.
              </span>
            </div>

            <div className="form-group" style={{ flexDirection: "row", alignItems: "center", gap: "8px" }}>
              <input
                type="checkbox"
                id="galleryCheck"
                checked={useGallery}
                onChange={(e) => setUseGallery(e.target.checked)}
              />
              <label htmlFor="galleryCheck" style={{ fontSize: "12px", cursor: "pointer" }}>
                Enable Employee Gallery Matching (Face Anchor Authority)
              </label>
            </div>

            {useGallery && (
              <div className="form-group">
                <label className="form-label">Gallery Folder Path</label>
                <input
                  type="text"
                  value={galleryPath}
                  onChange={(e) => setGalleryPath(e.target.value)}
                  placeholder="gallery"
                />
                <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
                  Contains subfolders per employee (e.g. gallery/EMP001/front.jpg)
                </span>
              </div>
            )}
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading || isLocked || sources.length === 0}
            >
              {loading ? "Starting Process…" : "Start Inference"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
