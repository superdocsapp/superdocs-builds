import { useState, useEffect, useRef, useCallback } from "react";
import { fetchQueue, fetchAllPending, fetchRunProgress } from "@/services/approvalApi";
import { useQueueStore } from "@/stores/queueStore";
import { useRunProgressStore } from "@/stores/runProgressStore";

export interface PollingConfig {
  intervalMs: number; // default: 10_000
  enabled: boolean; // tied to document.visibilityState
  runId: string | null;
}

export interface PollingState {
  isPolling: boolean;
  lastFetchedAt: Date | null;
  error: Error | null;
  connectionLost: boolean;
}

export function usePolling(config: PollingConfig): PollingState {
  const { intervalMs, enabled, runId } = config;

  const [isPolling, setIsPolling] = useState(false);
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [connectionLost, setConnectionLost] = useState(false);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isMountedRef = useRef(true);

  const mergeItems = useQueueStore((state) => state.mergeItems);
  const setProgress = useRunProgressStore((state) => state.setProgress);

  const doFetch = useCallback(async () => {
    if (!runId) return;

    setIsPolling(true);
    try {
      let queueResponse;
      if (runId === "all") {
        // Cross-run "all pending" mode — skip progress fetch
        queueResponse = await fetchAllPending();
      } else {
        const [queueResp, progressResponse] = await Promise.all([
          fetchQueue(runId),
          fetchRunProgress(runId),
        ]);
        queueResponse = queueResp;
        setProgress(progressResponse);
      }

      if (!isMountedRef.current) return;

      mergeItems(queueResponse.items, queueResponse.total, queueResponse.pending);
      setLastFetchedAt(new Date());
      setError(null);
      setConnectionLost(false);
    } catch (err) {
      if (!isMountedRef.current) return;

      const fetchError = err instanceof Error ? err : new Error("Unknown polling error");
      setError(fetchError);
      setConnectionLost(true);
      // Preserve local state — do not clear stores on error
    } finally {
      if (isMountedRef.current) {
        setIsPolling(false);
      }
    }
  }, [runId, mergeItems, setProgress]);

  // Start/stop polling interval based on enabled + runId
  useEffect(() => {
    if (!enabled || !runId) {
      // Clear any existing interval
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    // Immediate fetch when starting
    doFetch();

    // Set up interval
    intervalRef.current = setInterval(doFetch, intervalMs);

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [enabled, runId, intervalMs, doFetch]);

  // Visibility change listener: pause on hidden, resume with immediate fetch on visible
  useEffect(() => {
    if (!enabled || !runId) return;

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        // Pause polling
        if (intervalRef.current !== null) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      } else if (document.visibilityState === "visible") {
        // Resume with immediate fetch
        doFetch();
        intervalRef.current = setInterval(doFetch, intervalMs);
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [enabled, runId, intervalMs, doFetch]);

  // Track mounted state for cleanup
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  return { isPolling, lastFetchedAt, error, connectionLost };
}
