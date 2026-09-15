import { useCallback, useEffect, useRef, useState } from "react";
import { Job, Source, Camera, api } from "../api";

export function useTelemetry(refreshInterval = 3000, enabled = true, initialJobId: string | null = null) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [apiConnected, setApiConnected] = useState<boolean>(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(initialJobId);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);
  const runningRef = useRef(false);

  const loadData = useCallback(async () => {
    if (!enabled || runningRef.current) return;
    runningRef.current = true;
    const generation = ++generationRef.current;
    try {
      const [allJobs, allSources] = await Promise.all([api.jobs(), api.sources()]);
      if (generation !== generationRef.current) return;
      setJobs(allJobs);
      setSources(allSources);
      setApiConnected(true);
      setError(null);
    } catch (cause: any) {
      if (generation !== generationRef.current) return;
      setApiConnected(false);
      setError(cause.message || "Backend request failed");
    } finally {
      if (generation === generationRef.current) setLoading(false);
      runningRef.current = false;
    }
  }, [enabled]);

  const loadCameras = useCallback(async () => {
    if (!enabled) return;
    try {
      setCameras(await api.cameras());
    } catch {
      setCameras([]);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      generationRef.current += 1;
      setJobs([]);
      setSources([]);
      setCameras([]);
      setApiConnected(false);
      setLoading(true);
      return;
    }
    let cancelled = false;
    let timer: number | null = null;
    const tick = async () => {
      await loadData();
      if (!cancelled) timer = window.setTimeout(tick, refreshInterval);
    };
    tick();
    loadCameras();
    return () => {
      cancelled = true;
      generationRef.current += 1;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [enabled, loadData, loadCameras, refreshInterval]);

  const activeJob = jobs.find((job) => ["STARTING", "RUNNING", "FINALIZING", "CANCEL_REQUESTED"].includes(job.status)) ?? null;
  const queuedJobs = jobs.filter((job) => job.status === "QUEUED");
  const historyJobs = jobs.filter((job) => !["STARTING", "RUNNING", "FINALIZING", "CANCEL_REQUESTED", "QUEUED"].includes(job.status));
  const selectedJob = selectedJobId ? jobs.find((job) => job.id === selectedJobId) ?? null : null;
  const selectedJobMissing = !loading && selectedJobId !== null && selectedJob === null;

  return {
    jobs,
    sources,
    cameras,
    activeJob,
    queuedJobs,
    historyJobs,
    selectedJob,
    selectedJobId,
    selectedJobMissing,
    setSelectedJobId,
    apiConnected,
    isLocked: activeJob !== null,
    loading,
    error,
    refresh: loadData,
    refreshCameras: loadCameras,
  };
}
