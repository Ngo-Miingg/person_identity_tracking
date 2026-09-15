import { useState, useEffect, useRef } from "react";
import "./globals.css";
import "./components/layout/layout.css";
import { Header } from "./components/layout/Header";
import { Sidebar, NavView } from "./components/layout/Sidebar";
import { Footer } from "./components/layout/Footer";
import { LiveMonitorView } from "./components/live/LiveMonitorView";
import { IdentityHubView } from "./components/identity/IdentityHubView";
import { ModelPipelineView } from "./components/pipeline/ModelPipelineView";
import { ArchiveView } from "./components/archive/ArchiveView";
import { SourceManagerView } from "./components/sources/SourceManagerView";
import { LaunchJobModal } from "./components/sources/LaunchJobModal";
import { useTelemetry } from "./hooks/useTelemetry";
import { api } from "./api";

function getHashParams(): { view?: NavView; job?: string } {
  try {
    const raw = window.location.hash.replace(/^#\/?/, "");
    const params = new URLSearchParams(raw);
    const v = params.get("view") as NavView;
    const j = params.get("job") || undefined;
    const validViews: NavView[] = ["live", "identities", "pipeline", "archive", "sources"];
    return {
      view: validViews.includes(v) ? v : undefined,
      job: j,
    };
  } catch {
    return {};
  }
}

function App() {
  const initialRef = useRef(getHashParams());
  const initial = initialRef.current;
  const [currentView, setCurrentView] = useState<NavView>(initial.view || "live");
  const [isLaunchModalOpen, setIsLaunchModalOpen] = useState<boolean>(false);
  const [launchSourceId, setLaunchSourceId] = useState<string | null>(null);
  const autoLaunchAttempted = useRef(false);

  const {
    jobs,
    sources,
    cameras,
    activeJob,
    selectedJob,
    selectedJobId,
    selectedJobMissing,
    setSelectedJobId,
    apiConnected,
    isLocked,
    refresh,
    loading,
  } = useTelemetry(2500, true, initial.job ?? null);

  // Sync hash state with view and selected job
  useEffect(() => {
    const p = new URLSearchParams();
    p.set("view", currentView);
    if (selectedJobId) p.set("job", selectedJobId);
    const newHash = `#${p.toString()}`;
    if (window.location.hash !== newHash) {
      window.history.replaceState(null, "", newHash);
    }
  }, [currentView, selectedJobId]);

  // Handle browser back/forward buttons
  useEffect(() => {
    const handleHashChange = () => {
      const parsed = getHashParams();
      setCurrentView(parsed.view || "live");
      setSelectedJobId(parsed.job || null);
    };
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, [setSelectedJobId]);

  // A URL without a job gets the active session. A requested, missing job is never replaced.
  useEffect(() => {
    if (loading || !selectedJob || !initial.job || selectedJob.status !== "QUEUED") return;
    const active = jobs.find((job) => ["STARTING", "RUNNING", "FINALIZING", "CANCEL_REQUESTED"].includes(job.status));
    if (active && active.id !== selectedJob.id) setSelectedJobId(active.id);
  }, [initial.job, jobs, loading, selectedJob, selectedJobId, setSelectedJobId]);

  useEffect(() => {
    if (loading || selectedJobId || initial.job || jobs.length === 0) return;
    const active = jobs.find((job) => ["STARTING", "RUNNING", "FINALIZING", "CANCEL_REQUESTED"].includes(job.status));
    if (active) setSelectedJobId(active.id);
  }, [initial.job, jobs, loading, selectedJobId, setSelectedJobId]);

  // Refreshing the console must never launch a new RTSP inference worker.
  // A camera job is started explicitly from the source/job controls so a
  // disconnected camera cannot create a hanging Python process on every F5.
  useEffect(() => {
    if (loading || !apiConnected || initial.job || selectedJobId || autoLaunchAttempted.current) return;
    const hikvision = sources.find(
      (source) => source.kind === "rtsp" && source.uri.includes("172.16.16.27") && source.uri.includes("/Streaming/Channels/101"),
    ) || sources.find((source) => source.kind === "rtsp");
    if (!hikvision) return;
    const existing = jobs.find((job) =>
      ["STARTING", "RUNNING", "FINALIZING", "CANCEL_REQUESTED", "QUEUED"].includes(job.status)
      && job.source_kind === "rtsp"
      && job.source.includes("172.16.16.27"),
    );
    autoLaunchAttempted.current = true;
    if (existing) {
      setSelectedJobId(existing.id);
      setCurrentView("live");
      return;
    }
    autoLaunchAttempted.current = true;
    void hikvision;
  }, [apiConnected, initial.job, jobs, loading, refresh, selectedJobId, sources]);

  const handleJobStarted = (jobId: string) => {
    setSelectedJobId(jobId);
    setCurrentView("live");
    refresh();
  };

  return (
    <div className="app-shell">
      {/* Top Telemetry & Control Header */}
      <Header
        apiConnected={apiConnected}
        activeJob={activeJob}
        selectedJob={selectedJob}
        jobs={jobs}
        onSelectJobId={setSelectedJobId}
        onOpenNewJobModal={() => setIsLaunchModalOpen(true)}
      />

      <div className="app-container">
        {/* Left Operations Activity Sidebar */}
        <Sidebar
          currentView={currentView}
          onNavigate={setCurrentView}
          isRunning={activeJob !== null}
          profileCount={0}
          jobCount={jobs.length}
          sourceCount={sources.length}
        />

        {/* Dynamic Workspace */}
        <main className="app-content">
          {selectedJobMissing && (
            <div className="panel empty-state">
              <h3>Job not found</h3>
              <p>The requested job <code>{selectedJobId}</code> does not exist or is no longer available.</p>
            </div>
          )}

           {/* Keep the live player mounted while navigating so the MJPEG connection
               and its decoder are not reset when returning to the home view. */}
           {!selectedJobMissing && (
             <div style={{ display: currentView === "live" ? "block" : "none", height: "100%" }}>
               <LiveMonitorView
                 selectedJob={selectedJob}
                 onJobUpdated={refresh}
                 onSelectJobId={setSelectedJobId}
               />
             </div>
           )}

          {!selectedJobMissing && currentView === "identities" && (
            <IdentityHubView
              selectedJob={selectedJob}
            />
          )}

          {!selectedJobMissing && currentView === "pipeline" && (
            <ModelPipelineView
              selectedJob={selectedJob}
            />
          )}

          {currentView === "archive" && (
            <ArchiveView
              jobs={jobs}
              selectedJobId={selectedJobId}
              onSelectJobId={setSelectedJobId}
              onJobUpdated={refresh}
            />
          )}

          {currentView === "sources" && (
            <SourceManagerView
              sources={sources}
              cameras={cameras}
              onSourcesUpdated={refresh}
               onLaunchWithSource={(sourceId) => {
                 setLaunchSourceId(sourceId);
                 setIsLaunchModalOpen(true);
              }}
              isLocked={isLocked}
            />
          )}
        </main>
      </div>

      {/* Realtime Bottom Telemetry Footer */}
      <Footer
        activeJob={activeJob}
        selectedJob={selectedJob}
      />

      {/* Inference Job Creator Modal */}
      <LaunchJobModal
        sources={sources}
        initialSourceId={launchSourceId}
        isOpen={isLaunchModalOpen}
        onClose={() => {
          setIsLaunchModalOpen(false);
          setLaunchSourceId(null);
        }}
        onJobStarted={handleJobStarted}
        isLocked={isLocked}
      />
    </div>
  );
}

export default App;
