import { useEffect, useRef, useState } from "react";
import { Job, getWsUrl, api } from "../api";

export type WebSocketStatus = "connecting" | "open" | "polling" | "closed" | "error";

export function useJobWebSocket(jobId: string | null | undefined, onUpdate?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [status, setStatus] = useState<WebSocketStatus>("closed");
  const callbackRef = useRef(onUpdate);
  callbackRef.current = onUpdate;

  useEffect(() => {
    setJob(null);
    if (!jobId) {
      setStatus("closed");
      return;
    }

    let cancelled = false;
    let terminal = false;
    let socket: WebSocket | null = null;
    let pollTimer: number | null = null;
    let watchdog: number | null = null;
    let receivedWsFrame = false;

    const apply = (incoming: Job) => {
      if (cancelled || incoming.id !== jobId) return;
      setJob(incoming);
      callbackRef.current?.(incoming);
      terminal = ["COMPLETED", "FAILED", "STOPPED"].includes(incoming.status);
      if (terminal && pollTimer !== null) {
        window.clearTimeout(pollTimer);
        pollTimer = null;
      }
    };

    const poll = async () => {
      if (cancelled || terminal || receivedWsFrame) return;
      setStatus("polling");
      try {
        apply(await api.getJob(jobId));
      } catch {
        if (!cancelled) setStatus("error");
      }
      if (!cancelled && !terminal && !receivedWsFrame) {
        pollTimer = window.setTimeout(poll, 2500);
      }
    };

    api.getJob(jobId).then(apply).catch(() => undefined);
    setStatus("connecting");
    try {
      socket = new WebSocket(getWsUrl(jobId));
      socket.onopen = () => {
        if (!cancelled) setStatus("open");
      };
      socket.onmessage = (event) => {
        try {
          const incoming = JSON.parse(event.data) as Job;
          if (incoming.id !== jobId) return;
          receivedWsFrame = true;
          if (pollTimer !== null) window.clearTimeout(pollTimer);
          pollTimer = null;
          if (watchdog !== null) window.clearTimeout(watchdog);
          watchdog = null;
          setStatus("open");
          apply(incoming);
        } catch {
          setStatus("error");
        }
      };
      socket.onerror = () => {
        receivedWsFrame = false;
        poll();
      };
      socket.onclose = () => {
        if (cancelled || terminal) {
          setStatus("closed");
          return;
        }
        receivedWsFrame = false;
        poll();
      };
      watchdog = window.setTimeout(() => {
        if (!receivedWsFrame && !terminal) poll();
      }, 3500);
    } catch {
      poll();
    }

    return () => {
      cancelled = true;
      socket?.close();
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      if (watchdog !== null) window.clearTimeout(watchdog);
    };
  }, [jobId]);

  return { job, status };
}
