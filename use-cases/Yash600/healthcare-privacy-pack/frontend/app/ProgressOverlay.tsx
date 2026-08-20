"use client";

// ProgressOverlay.tsx -- a reusable "what's happening right now" box for
// every upload/update action in this app (document upload, Analyze
// References, Update-request submission, approve/reject). Two rules this
// component and its hook are built to never violate, since a progress
// indicator that lies is worse than none at all:
//
//   1. It never shows a stage as "done" before the real network call behind
//      it has actually resolved. For a single blocking request (Analyze
//      References, Submit, Approve/Reject) we don't get incremental signal
//      from the backend, so intermediate stages auto-advance on a timer for
//      *readability* but always HOLD at the final "in progress" stage --
//      never marked done -- until the real promise settles. For the
//      multi-file upload flow we have genuine per-file signal (each file is
//      its own awaited request), so every stage there reflects a real
//      network call that has actually completed, not a guess.
//   2. It never closes itself before the operation is actually finished or
//      failed, and on failure it stays open showing exactly which stage
//      failed and why, rather than silently vanishing.

import { useEffect, useRef, useState } from "react";
import { IconCheckCircle, IconX, IconAlertTriangle } from "./icons";

export type StageStatus = "pending" | "active" | "done" | "error";

function Spinner() {
  return <span className="stage-spinner" aria-hidden="true" />;
}

function StageIcon({ status }: { status: StageStatus }) {
  if (status === "done") return <IconCheckCircle size={15} className="stage-icon-done" />;
  if (status === "error") return <IconX size={15} className="stage-icon-error" />;
  if (status === "active") return <Spinner />;
  return <span className="stage-icon-pending" aria-hidden="true" />;
}

export function ProgressOverlay({
  visible,
  title,
  labels,
  statuses,
  detail,
  error,
  onDismiss,
}: {
  visible: boolean;
  title: string;
  labels: string[];
  statuses: StageStatus[];
  detail?: string | null;
  error?: string | null;
  onDismiss: () => void;
}) {
  if (!visible) return null;
  return (
    <div className="progress-overlay-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className="progress-overlay-card">
        <div className="progress-overlay-title">{title}</div>
        <div className="progress-overlay-stages">
          {labels.map((label, i) => (
            <div key={i} className={`progress-stage ${statuses[i]}`}>
              <StageIcon status={statuses[i]} />
              <span>{label}</span>
            </div>
          ))}
        </div>
        {detail && !error && <div className="progress-overlay-detail">{detail}</div>}
        {error && (
          <div className="progress-overlay-error">
            <IconAlertTriangle size={14} />
            <span>{error}</span>
          </div>
        )}
        {error && (
          <button className="btn" style={{ marginTop: 12, width: "100%", justifyContent: "center" }} onClick={onDismiss}>
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Drives a ProgressOverlay. Two ways to use it:
 *
 *   - runStaged(title, labels, task): for a single opaque request (no
 *     incremental backend signal). Stages before the last one auto-advance
 *     on a readable cadence purely as narration; the LAST stage is held
 *     "active" for as long as the real request takes, and only flips to
 *     "done" once it actually resolves. Throws through so the caller's own
 *     try/catch and error state still work exactly as before.
 *
 *   - start/setStageStatus/finish/fail/close: for a sequence of genuinely
 *     separate awaited calls (the multi-file upload loop), where each stage
 *     really does correspond to one real request settling.
 */
export function useStagedProgress() {
  const [visible, setVisible] = useState(false);
  const [title, setTitle] = useState("");
  const [labels, setLabels] = useState<string[]>([]);
  const [statuses, setStatuses] = useState<StageStatus[]>([]);
  const [detail, setDetail] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current);
  }, []);

  function stopTimer() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }

  function start(t: string, stageLabels: string[], d?: string) {
    stopTimer();
    setTitle(t);
    setLabels(stageLabels);
    setStatuses(stageLabels.map((_, i) => (i === 0 ? "active" : "pending")));
    setDetail(d ?? null);
    setError(null);
    setVisible(true);
  }

  /** Auto-advances through stages, but refuses to ever mark the final stage
   * done -- it holds there (still spinning) until finish()/fail() is called
   * for real. */
  function advanceOptimistically(intervalMs = 1100) {
    stopTimer();
    timerRef.current = setInterval(() => {
      setStatuses((prev) => {
        const lastIndex = prev.length - 1;
        const activeIndex = prev.findIndex((s) => s === "active");
        if (activeIndex === -1 || activeIndex >= lastIndex) return prev; // already holding on the last stage
        const next = [...prev];
        next[activeIndex] = "done";
        next[activeIndex + 1] = "active";
        return next;
      });
    }, intervalMs);
  }

  function setStageStatus(index: number, status: StageStatus) {
    setStatuses((prev) => {
      const next = [...prev];
      next[index] = status;
      return next;
    });
  }

  function setDetailText(d: string | null) {
    setDetail(d);
  }

  function finish(closeAfterMs = 500) {
    stopTimer();
    setStatuses((prev) => prev.map(() => "done" as StageStatus));
    setDetail(null);
    if (closeAfterMs > 0) {
      setTimeout(() => setVisible(false), closeAfterMs);
    }
  }

  function fail(message: string, atIndex?: number) {
    stopTimer();
    setError(message);
    setStatuses((prev) => {
      const idx = atIndex ?? prev.findIndex((s) => s === "active");
      if (idx < 0) return prev;
      const next = [...prev];
      next[idx] = "error";
      return next;
    });
  }

  function close() {
    stopTimer();
    setVisible(false);
  }

  /** Runs a single opaque async task behind the "optimistic advance, hold
   * the last stage for real" pattern described above. Rethrows on failure
   * so existing setError()/catch blocks in each page keep working. */
  async function runStaged<T>(t: string, stageLabels: string[], task: () => Promise<T>, opts?: { cadenceMs?: number; detail?: string }): Promise<T> {
    start(t, stageLabels, opts?.detail);
    advanceOptimistically(opts?.cadenceMs);
    try {
      const result = await task();
      finish();
      return result;
    } catch (e) {
      fail(String(e));
      throw e;
    }
  }

  return {
    visible,
    title,
    labels,
    statuses,
    detail,
    error,
    start,
    advanceOptimistically,
    setStageStatus,
    setDetailText,
    finish,
    fail,
    close,
    runStaged,
  };
}
