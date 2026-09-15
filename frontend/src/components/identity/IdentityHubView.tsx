import React, { useState, useEffect, useMemo } from "react";
import { Job, api, IdentityProfile, getAbsoluteUrl } from "../../api";
import "./identity.css";

interface IdentityHubViewProps {
  selectedJob: Job | null;
}

export const IdentityHubView: React.FC<IdentityHubViewProps> = ({ selectedJob }) => {
  const [profiles, setProfiles] = useState<IdentityProfile[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPersonId, setSelectedPersonId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const jobId = selectedJob?.id ?? null;

  useEffect(() => {
    if (!jobId) {
      setProfiles([]);
      setSelectedPersonId(null);
      setLoading(false);
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError(null);

    api
      .identities(jobId)
      .then((data) => {
        if (!isMounted) return;
        setProfiles(data.profiles || []);
        if (data.profiles && data.profiles.length > 0) {
          setSelectedPersonId((prev) => {
            if (prev && data.profiles.some((p) => p.person_id === prev)) return prev;
            return data.profiles[0].person_id;
          });
        } else {
          setSelectedPersonId(null);
        }
      })
      .catch((err) => {
        if (!isMounted) return;
        setError(err.message || "Failed to load identity memory profiles");
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [jobId]);

  const filteredProfiles = useMemo(() => {
    if (!searchQuery.trim()) return profiles;
    const q = searchQuery.toLowerCase();
    return profiles.filter(
      (p) =>
        p.person_id.toLowerCase().includes(q) ||
        (p.employee_id && p.employee_id.toLowerCase().includes(q))
    );
  }, [profiles, searchQuery]);

  const activeProfile = useMemo(() => {
    return profiles.find((p) => p.person_id === selectedPersonId) || profiles[0] || null;
  }, [profiles, selectedPersonId]);

  if (!selectedJob) {
    return (
      <div className="panel" style={{ margin: "20px", height: "calc(100% - 40px)", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", color: "var(--text-muted)" }}>
          <h3>No Session Selected</h3>
          <p style={{ fontSize: "12px", marginTop: "4px" }}>Select a session from the top bar to inspect learned biometric profiles.</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="panel" style={{ margin: "20px", height: "calc(100% - 40px)", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", color: "var(--text-muted)" }}>
          <span className="badge-dot pulsing-live" style={{ background: "var(--color-cyan)", marginBottom: "8px" }} />
          <h3>Loading Biometric Memory Profiles…</h3>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel" style={{ margin: "20px", height: "calc(100% - 40px)", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", color: "var(--color-crimson)" }}>
          <h3>Failed to Load Profiles</h3>
          <p style={{ fontSize: "12px", marginTop: "4px" }}>{error}</p>
        </div>
      </div>
    );
  }

  if (profiles.length === 0) {
    return (
      <div className="panel" style={{ margin: "20px", height: "calc(100% - 40px)", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", color: "var(--text-muted)" }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ marginBottom: "12px", opacity: 0.5 }}>
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
          </svg>
          <h3>No Persistent Identity Profiles</h3>
          <p style={{ fontSize: "12px", marginTop: "4px" }}>
            This completed session produced no persistent face-anchored profiles. This is distinct from having no detections or tracklets.
          </p>
          <p style={{ fontSize: "11px", marginTop: "8px", color: "var(--text-dim)" }}>
            Job status: {selectedJob.status} · Track rows: {selectedJob.progress.rows}
          </p>
        </div>
      </div>
    );
  }

  // Filter face samples into 3 pose angle buckets
  const leftPoses = activeProfile?.face_memory.filter((s) => s.pose === "left") || [];
  const frontPoses = activeProfile?.face_memory.filter((s) => s.pose === "front" || !s.pose) || [];
  const rightPoses = activeProfile?.face_memory.filter((s) => s.pose === "right") || [];
  const heroFace = frontPoses[0] || activeProfile?.face_memory[0];

  return (
    <div className="identity-container">
      {/* Profiles Selection Sidebar */}
      <div className="panel profiles-sidebar">
        <div className="search-box">
          <input
            type="text"
            className="search-input"
            placeholder="Search by ID (e.g. P001, EMP001)…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="profiles-list">
          {filteredProfiles.map((p) => {
            const thumb = p.face_memory[0]?.image_url;
            const isSelected = p.person_id === selectedPersonId;

            return (
              <div
                key={p.person_id}
                className={`profile-card ${isSelected ? "active" : ""}`}
                onClick={() => setSelectedPersonId(p.person_id)}
              >
                <div className="profile-avatar">
                  {thumb ? (
                    <img src={getAbsoluteUrl(thumb)} alt={p.person_id} />
                  ) : (
                    <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>N/A</span>
                  )}
                </div>

                <div className="profile-info">
                  <div className="profile-name-row">
                    <span className="profile-id">{p.person_id}</span>
                    {p.employee_id ? (
                      <span className="badge badge-emerald">{p.employee_id}</span>
                    ) : (
                      <span className={`badge ${p.maturity === "STABLE" ? "badge-cyan" : "badge-amber"}`}>
                        {p.maturity}
                      </span>
                    )}
                  </div>
                  <div className="profile-stats">
                    <span>{p.face_observations} faces</span>
                    <span>·</span>
                    <span>{p.body_observations} bodies</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Biometric Dossier Main Panel */}
      {activeProfile && (
        <div className="panel dossier-panel">
          {/* Hero Profile Header */}
          <div className="dossier-hero">
            <div className="dossier-hero-left">
              <div className="dossier-hero-avatar">
                {heroFace ? (
                  <img src={getAbsoluteUrl(heroFace.image_url)} alt={activeProfile.person_id} />
                ) : (
                  <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-dim)" }}>
                    NO AVATAR
                  </div>
                )}
              </div>
              <div className="dossier-titles">
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <span className="dossier-title-main">{activeProfile.person_id}</span>
                  {activeProfile.employee_id ? (
                    <span className="badge badge-emerald">CONFIRMED: {activeProfile.employee_id}</span>
                  ) : (
                    <span className="badge badge-amber">ANONYMOUS RECOGNITION</span>
                  )}
                  <span className="badge badge-cyan">{activeProfile.maturity}</span>
                </div>
                <div style={{ fontSize: "11px", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                  Confidence Score: <b>{(activeProfile.confidence * 100).toFixed(1)}%</b> · Conflicts: <b>{activeProfile.conflict_count}</b>
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: "8px" }}>
              <span className="badge badge-violet">{activeProfile.face_vectors} Face Vectors (AdaFace)</span>
              <span className="badge badge-violet">{activeProfile.body_vectors} Body Vectors (OSNet)</span>
            </div>
          </div>

          {/* Metrics Grid */}
          <div className="dossier-metrics-grid">
            <div className="metric-card">
              <span className="metric-label">Face Anchor Count</span>
              <span className="metric-value">{activeProfile.face_anchor_count}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">Face Observations</span>
              <span className="metric-value">{activeProfile.face_observations}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">Body ReID Observations</span>
              <span className="metric-value">{activeProfile.body_observations}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">Associated Cameras</span>
              <span className="metric-value" style={{ fontSize: "14px" }}>
                {activeProfile.members.length > 0
                  ? activeProfile.members.map((m) => `${m.camera} (T#${m.track_id})`).join(", ")
                  : "Internal track"}
              </span>
            </div>
          </div>

          {/* AdaFace Multi-Angle Matrix */}
          <div className="matrix-section">
            <div className="panel-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="2" y1="12" x2="22" y2="12"></line>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1 4-10z"></path>
              </svg>
              AdaFace IR50 Biometric Multi-Angle Matrix (Pose-Specific Prototype Views)
            </div>

            <div className="matrix-grid">
              {/* Left Column */}
              <div className="pose-column">
                <div className="pose-header">
                  <span>LEFT YAW (&lt; -0.25)</span>
                  <span className="badge badge-cyan">{leftPoses.length} crops</span>
                </div>
                <div className="pose-gallery">
                  {leftPoses.slice(0, 4).map((crop, idx) => (
                    <div key={idx} className="crop-card">
                      <img src={getAbsoluteUrl(crop.image_url)} alt="Left face pose" />
                      <span className="crop-overlay-tag">Q: {(crop.quality * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                  {leftPoses.length === 0 && (
                    <div style={{ gridColumn: "span 2", textAlign: "center", padding: "20px 0", color: "var(--text-dim)", fontSize: "11px" }}>
                      No left-angle views recorded
                    </div>
                  )}
                </div>
              </div>

              {/* Front Column */}
              <div className="pose-column">
                <div className="pose-header">
                  <span>FRONTAL (Direct View)</span>
                  <span className="badge badge-emerald">{frontPoses.length} crops</span>
                </div>
                <div className="pose-gallery">
                  {frontPoses.slice(0, 4).map((crop, idx) => (
                    <div key={idx} className="crop-card">
                      <img src={getAbsoluteUrl(crop.image_url)} alt="Front face pose" />
                      <span className="crop-overlay-tag">Q: {(crop.quality * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                  {frontPoses.length === 0 && (
                    <div style={{ gridColumn: "span 2", textAlign: "center", padding: "20px 0", color: "var(--text-dim)", fontSize: "11px" }}>
                      No frontal views recorded
                    </div>
                  )}
                </div>
              </div>

              {/* Right Column */}
              <div className="pose-column">
                <div className="pose-header">
                  <span>RIGHT YAW (&gt; +0.25)</span>
                  <span className="badge badge-cyan">{rightPoses.length} crops</span>
                </div>
                <div className="pose-gallery">
                  {rightPoses.slice(0, 4).map((crop, idx) => (
                    <div key={idx} className="crop-card">
                      <img src={getAbsoluteUrl(crop.image_url)} alt="Right face pose" />
                      <span className="crop-overlay-tag">Q: {(crop.quality * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                  {rightPoses.length === 0 && (
                    <div style={{ gridColumn: "span 2", textAlign: "center", padding: "20px 0", color: "var(--text-dim)", fontSize: "11px" }}>
                      No right-angle views recorded
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* OSNet Body ReID Wardrobe */}
          <div className="wardrobe-section">
            <div className="panel-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20.38 3.46L16 2a4 4 0 0 1-8 0L3.62 3.46a2 2 0 0 0-1.34 2.23l.58 3.47a1 1 0 0 0 .99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V10h2.15a1 1 0 0 0 .99-.84l.58-3.47a2 2 0 0 0-1.34-2.23z"></path>
              </svg>
              OSNet x1.0 Body ReID Appearance Wardrobe (Continuity Reservoir)
            </div>

            <div className="wardrobe-grid">
              {activeProfile.body_memory && activeProfile.body_memory.length > 0 ? (
                activeProfile.body_memory.map((body, idx) => (
                  <div key={idx} className="body-crop-card">
                    <img src={getAbsoluteUrl(body.image_url)} alt={`Body sample #${idx}`} />
                    <span className="crop-overlay-tag" style={{ color: "var(--color-violet)" }}>
                      Q: {(body.quality * 100).toFixed(0)}%
                    </span>
                  </div>
                ))
              ) : (
                <div style={{ color: "var(--text-dim)", fontSize: "11px", padding: "10px 0" }}>
                  No body crops archived for this identity profile.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
