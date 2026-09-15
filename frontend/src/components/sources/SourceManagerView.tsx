import React, { useState, useRef } from "react";
import { Source, Camera, api } from "../../api";
import "./sources.css";

interface SourceManagerViewProps {
  sources: Source[];
  cameras: Camera[];
  onSourcesUpdated: () => void;
  onLaunchWithSource: (sourceId: string) => void;
  isLocked: boolean;
}

export const SourceManagerView: React.FC<SourceManagerViewProps> = ({
  sources,
  cameras,
  onSourcesUpdated,
  onLaunchWithSource,
  isLocked,
}) => {
  const [uploading, setUploading] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<boolean>(false);

  // RTSP form state
  const [rtspName, setRtspName] = useState<string>("");
  const [rtspUri, setRtspUri] = useState<string>("");
  const [rtspLoc, setRtspLoc] = useState<string>("");
  const [submittingRtsp, setSubmittingRtsp] = useState<boolean>(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (file: File) => {
    setError(null);
    setUploading(true);
    setUploadProgress(`Uploading ${file.name}…`);

    try {
      const uploadRes = await api.upload(file);
      setUploadProgress("Registering source…");

      await api.addSource({
        name: file.name.replace(/\.[^/.]+$/, ""),
        kind: "upload",
        uri: uploadRes.id,
        location: "Local Upload Storage",
        enabled: true,
      });

      onSourcesUpdated();
      setUploadProgress(null);
    } catch (err: any) {
      setError(err.message || "Failed to upload video source");
      setUploadProgress(null);
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteSource = async (id: string) => {
    if (!window.confirm("Are you sure you want to remove this source?")) return;
    try {
      await api.deleteSource(id);
      onSourcesUpdated();
    } catch (err: any) {
      setError(err.message || "Failed to remove source");
    }
  };

  const handleAddWebcam = async (cam: Camera) => {
    try {
      await api.addSource({
        name: cam.label,
        kind: "webcam",
        uri: String(cam.index),
        location: `DirectShow Index #${cam.index}`,
        enabled: true,
      });
      onSourcesUpdated();
    } catch (err: any) {
      setError(err.message || "Failed to register camera");
    }
  };

  const handleAddRtsp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rtspName.trim() || !rtspUri.trim()) return;

    setSubmittingRtsp(true);
    setError(null);

    try {
      await api.addSource({
        name: rtspName.trim(),
        kind: "rtsp",
        uri: rtspUri.trim(),
        location: rtspLoc.trim() || "Network Stream",
        enabled: true,
      });
      setRtspName("");
      setRtspUri("");
      setRtspLoc("");
      onSourcesUpdated();
    } catch (err: any) {
      setError(err.message || "Failed to register RTSP source");
    } finally {
      setSubmittingRtsp(false);
    }
  };

  return (
    <div className="sources-container">
      {error && (
        <div style={{ padding: "10px 14px", background: "var(--color-crimson-glow)", border: "1px solid var(--color-crimson-border)", color: "var(--color-crimson)", borderRadius: "var(--radius-sm)", fontSize: "12px" }}>
          {error}
        </div>
      )}

      {/* Top section: Upload Dropzone & Discovery */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
        {/* Upload Dropzone */}
        <div
          className={`dropzone-box ${dragOver ? "dragover" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            if (e.dataTransfer.files?.[0]) {
              handleFileUpload(e.dataTransfer.files[0]);
            }
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: "none" }}
            accept=".mp4,.avi,.mov,.mkv,.webm"
            onChange={(e) => {
              if (e.target.files?.[0]) handleFileUpload(e.target.files[0]);
            }}
          />
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ color: "var(--color-cyan)" }}>
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="17 8 12 3 7 8"></polyline>
            <line x1="12" y1="3" x2="12" y2="15"></line>
          </svg>
          <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>
            {uploading ? uploadProgress : "Upload Test Video for Tracking"}
          </div>
          <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
            Drag & drop MP4, AVI, MOV, MKV, or click to browse (up to 2GB)
          </div>
        </div>

        {/* Hardware Webcam Discovery Card */}
        <div className="camera-probe-card">
          <div className="panel-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
              <circle cx="12" cy="13" r="4"></circle>
            </svg>
            DirectShow Hardware Cameras ({cameras.length} probed)
          </div>

          <div className="camera-grid">
            {cameras.map((cam) => {
              const registeredSource = sources.find(
                (s) => s.kind === "webcam" && s.uri === String(cam.index)
              );
              const alreadyRegistered = Boolean(registeredSource);

              return (
                <div key={cam.index} className="camera-item">
                  <div style={{ fontWeight: 600, fontSize: "12px" }}>{cam.label}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-muted)" }}>
                    Index #{cam.index} · {cam.width}x{cam.height}
                  </div>
                  <button
                    className="btn btn-secondary"
                    style={{ marginTop: "4px", fontSize: "10px", padding: "3px 6px" }}
                    onClick={() => registeredSource ? onLaunchWithSource(registeredSource.id) : handleAddWebcam(cam)}
                    disabled={isLocked}
                    title={isLocked ? "Inference lock active" : alreadyRegistered ? "Open launch dialog with this camera selected" : "Register this camera as a source"}
                  >
                    {alreadyRegistered ? "Use Camera" : "+ Register Source"}
                  </button>
                </div>
              );
            })}

            {cameras.length === 0 && (
              <div style={{ color: "var(--text-dim)", fontSize: "11px" }}>
                No DirectShow cameras probed on backend ports 0–5.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Network Stream (RTSP) Registration Form */}
      <div className="panel" style={{ padding: "14px 16px" }}>
        <div className="panel-title" style={{ marginBottom: "10px" }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="2" y1="12" x2="22" y2="12"></line>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
          </svg>
          Register Network Stream (RTSP / HTTP)
        </div>

        <form onSubmit={handleAddRtsp} style={{ display: "flex", gap: "10px", alignItems: "flex-end" }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Stream Name</label>
            <input
              type="text"
              placeholder="e.g. Entrance IP Camera"
              value={rtspName}
              onChange={(e) => setRtspName(e.target.value)}
              required
            />
          </div>
          <div className="form-group" style={{ flex: 2 }}>
            <label className="form-label">RTSP / HTTP URL</label>
            <input
              type="text"
              placeholder="rtsp://admin:pass@192.168.1.100:554/live"
              value={rtspUri}
              onChange={(e) => setRtspUri(e.target.value)}
              required
            />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Location</label>
            <input
              type="text"
              placeholder="e.g. Building A Lobby"
              value={rtspLoc}
              onChange={(e) => setRtspLoc(e.target.value)}
            />
          </div>
          <button type="submit" className="btn btn-secondary" disabled={submittingRtsp} style={{ height: "34px" }}>
            {submittingRtsp ? "Registering…" : "+ Add Stream"}
          </button>
        </form>
      </div>

      {/* Fleet of Registered Sources */}
      <div className="panel" style={{ padding: "16px", gap: "12px" }}>
        <div className="panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect>
            <rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect>
            <line x1="6" y1="6" x2="6.01" y2="6"></line>
            <line x1="6" y1="18" x2="6.01" y2="18"></line>
          </svg>
          Active Camera Fleet & Sources ({sources.length} sources registered)
        </div>

        <div className="sources-grid">
          {sources.map((s) => (
            <div key={s.id} className="source-card">
              <div className="source-card-header">
                <span className="source-title">{s.name}</span>
                <span className="badge badge-cyan">{s.kind}</span>
              </div>

              <div className="source-uri" title={s.uri}>
                {s.uri || "—"}
              </div>

              <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                Location: <b>{s.location || "Unspecified"}</b>
              </div>

              <div className="source-footer">
                <button
                  className="btn btn-primary"
                  style={{ padding: "4px 8px", fontSize: "11px" }}
                  onClick={() => onLaunchWithSource(s.id)}
                  disabled={isLocked}
                  title={isLocked ? "Inference lock active" : "Start a tracking job using this source"}
                >
                  ▶ Start Tracking
                </button>

                <button
                  className="btn btn-danger"
                  style={{ padding: "4px 8px", fontSize: "11px" }}
                  onClick={() => handleDeleteSource(s.id)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}

          {sources.length === 0 && (
            <div style={{ gridColumn: "span 3", textAlign: "center", padding: "30px", color: "var(--text-dim)" }}>
              No sources registered. Upload a video file or probe a local camera above.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
