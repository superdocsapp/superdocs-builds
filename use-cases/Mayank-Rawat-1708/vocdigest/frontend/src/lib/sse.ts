/**
 * @file src/lib/sse.ts
 * @description Live run updates. Subscribes to the backend's Server-Sent Events stream
 *   and falls back to polling when EventSource is unavailable or the stream errors, so
 *   the UI keeps updating rather than silently freezing on a dead connection.
 * @flow subscribeToRun() opens an EventSource -> "stage" events fire onUpdate ->
 *   "done" closes cleanly -> any error switches to a polling interval -> the returned
 *   function tears down whichever mechanism is active.
 * @dependencies ./api for the polling fallback and shared types
 */

import { api, type RunDetail } from "./api";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";
const POLL_INTERVAL_MS = 3000;

export interface StageEvent {
  run_id: string;
  status: string;
  current_stage: string | null;
  stages: Record<string, string>;
  updated_at: string;
}

/**
 * Subscribe to a run's progress. Returns an unsubscribe function.
 *
 * Starts on a 3-second poll and upgrades to SSE once the stream proves it can deliver
 * an event. Polling first means the view is never blank while a connection is
 * negotiated, and an SSE stream that connects but silently buffers — which some proxies
 * do, and which is indistinguishable from a hung backend — degrades to a working poll
 * rather than a frozen page. Any later stream error drops straight back to polling.
 */
export function subscribeToRun(
  runId: string,
  onUpdate: (detail: RunDetail) => void,
  onError?: (error: Error) => void,
): () => void {
  let cancelled = false;
  let source: EventSource | null = null;
  let pollTimer: number | null = null;

  const refresh = async () => {
    if (cancelled) return;
    try {
      const detail = await api.getRun(runId);
      if (!cancelled) onUpdate(detail);
      return detail;
    } catch (err) {
      if (!cancelled) onError?.(err as Error);
      return null;
    }
  };

  const startPolling = () => {
    if (pollTimer !== null || cancelled) return;
    void refresh();
    pollTimer = window.setInterval(async () => {
      const detail = await refresh();
      if (detail && (detail.status === "COMPLETE" || detail.status === "FAILED")) {
        stopPolling();
      }
    }, POLL_INTERVAL_MS);
  };

  const stopPolling = () => {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  // Poll first. The view populates immediately and keeps updating regardless of
  // whether the event stream ever works.
  startPolling();

  if (typeof EventSource !== "undefined") {
    try {
      source = new EventSource(`${BASE}/runs/${runId}/events`);

      source.addEventListener("stage", () => {
        // First delivered event proves the stream is live, so the poll can stop and
        // updates become push-driven.
        stopPolling();
        // The event payload is a summary; refetch full detail so the timeline, decision
        // log and cost figures all move together rather than in two visible steps.
        void refresh();
      });

      source.addEventListener("done", () => {
        void refresh();
        source?.close();
        source = null;
        stopPolling();
      });

      source.onerror = () => {
        source?.close();
        source = null;
        startPolling(); // back to polling; no-op if it is already running
      };
    } catch {
      // EventSource construction failed outright — polling is already running.
    }
  }

  return () => {
    cancelled = true;
    source?.close();
    stopPolling();
  };
}
