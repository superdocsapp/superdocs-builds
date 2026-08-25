/**
 * @file src/pages/RunDetail.tsx
 * @description Live view of one run: the stage timeline with decisions, the analysis
 *   summary, and the cost report. Subscribes to SSE with a polling fallback so progress
 *   keeps updating even where event streams are buffered by a proxy.
 * @flow mount -> subscribeToRun -> render timeline + summary -> route the user onward
 *   when the run pauses for approval or completes
 * @dependencies lib/sse, lib/api, StageTimeline, CostReport
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertCircle, ArrowRight, Loader2, RotateCw, Ban } from "lucide-react";
import { api, type CostReport as CostReportType, type RunDetail as Detail } from "../lib/api";
import { subscribeToRun } from "../lib/sse";
import { StageTimeline } from "../components/StageTimeline";
import { RunStatusBadge } from "../components/RunStatusBadge";
import { CostReport } from "../components/CostReport";

export default function RunDetail() {
  const { runId } = useParams<{ runId: string }>();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [cost, setCost] = useState<CostReportType | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    const unsubscribe = subscribeToRun(runId, setDetail, (e) => setError(e.message));
    return unsubscribe;
  }, [runId]);

  useEffect(() => {
    if (!runId || !detail) return;
    void api.getCost(runId).then(setCost).catch(() => {});
  }, [runId, detail?.updated_at]);

  const retry = async () => {
    if (!runId) return;
    await api.resumeRun(runId).catch((e) => setError((e as Error).message));
  };

  const retryStage = async (stage: string) => {
    if (!runId) return;
    await api.retryStage(runId, stage).catch((e) => setError((e as Error).message));
  };

  const skipStage = async (stage: string) => {
    if (!runId) return;
    await api.skipStage(runId, stage).catch((e) => setError((e as Error).message));
  };

  const cancel = async () => {
    if (!runId) return;
    // Confirm because cancelling is not resumable, unlike a pause.
    if (!window.confirm(
      "Cancel this run? It stops at the next stage boundary and cannot be resumed. " +
      "Completed stages are kept.",
    )) return;
    await api.cancelRun(runId).catch((e) => setError((e as Error).message));
  };

  const ACTIVE = new Set([
    "PENDING", "INGESTING", "CLASSIFYING", "EXTRACTING", "THEMING",
    "ANONYMIZING", "COMPARING", "DRAFTING", "UPLOADING",
  ]);

  if (error && !detail) return (
    <div className="card p-6 flex items-center gap-3 text-red-600">
      <AlertCircle className="w-5 h-5" /> {error}
    </div>
  );
  if (!detail) return (
    <div className="flex items-center gap-2 text-slate-500">
      <Loader2 className="w-4 h-4 animate-spin" /> Loading run…
    </div>
  );

  const s = detail.summary;
  return (
    <div className="space-y-6">
      <header className="flex items-start gap-4">
        <div className="flex-1">
          <h1 className="text-2xl font-semibold">{detail.quarter_label} digest</h1>
          <p className="text-xs text-slate-500 font-mono mt-1">{detail.id}</p>
        </div>
        {ACTIVE.has(detail.status) && (
          <button onClick={cancel} className="btn-danger text-sm" title="Stop this run spending tokens">
            <Ban className="w-4 h-4" /> Cancel
          </button>
        )}
        <RunStatusBadge status={detail.status} />
      </header>

      {detail.status === "AWAITING_APPROVAL" && (
        <Link to={`/runs/${detail.id}/approve`} className="card p-4 flex items-center gap-3 border-amber-300 hover:border-amber-400 transition">
          <div className="flex-1">
            <p className="font-medium text-amber-900 dark:text-amber-200">Waiting for your review</p>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {detail.pending_approvals} item{detail.pending_approvals === 1 ? "" : "s"} need a decision before publishing.
            </p>
          </div>
          <ArrowRight className="w-4 h-4" />
        </Link>
      )}

      {detail.status === "COMPLETE" && (
        <Link to={`/runs/${detail.id}/digest`} className="card p-4 flex items-center gap-3 border-emerald-300 hover:border-emerald-400 transition">
          <div className="flex-1">
            <p className="font-medium text-emerald-900 dark:text-emerald-200">Digest ready</p>
            <p className="text-sm text-slate-600 dark:text-slate-400">View the themes and download the document.</p>
          </div>
          <ArrowRight className="w-4 h-4" />
        </Link>
      )}

      {(detail.status === "FAILED" || detail.status === "PAUSED") && (
        <div className="card p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-medium">Run {detail.status.toLowerCase()}</p>
            <p className="text-sm text-slate-600 dark:text-slate-400">{detail.error_message ?? "See the timeline for detail."}</p>
          </div>
          <button onClick={retry} className="btn-ghost text-sm"><RotateCw className="w-4 h-4" /> Resume</button>
        </div>
      )}

      <section className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: "Ingested", value: s.conversations.ingested },
          { label: "Relevant", value: s.conversations.relevant },
          { label: "Excluded", value: s.conversations.skipped },
          { label: "Themes", value: s.themes },
          { label: "Quotes to review", value: s.quotes.needing_review },
        ].map((tile) => (
          <div key={tile.label} className="card p-4">
            <p className="text-xs text-slate-500">{tile.label}</p>
            <p className="text-xl font-semibold tabular-nums mt-1">{tile.value}</p>
          </div>
        ))}
      </section>

      {s.injection_attempts > 0 && (
        <div className="card p-4 text-sm border-amber-300">
          <strong>{s.injection_attempts}</strong> conversation{s.injection_attempts === 1 ? "" : "s"} contained
          text addressed to an automated system. It was recorded as data and not executed.
        </div>
      )}

      <section>
        <h2 className="font-semibold mb-3">Stages</h2>
        <StageTimeline
          timeline={detail.timeline}
          decisions={detail.decision_log}
          onRetry={retry}
          onRetryStage={retryStage}
          onSkipStage={skipStage}
        />
      </section>

      {cost && (
        <section>
          <h2 className="font-semibold mb-3">Cost</h2>
          <CostReport report={cost} />
        </section>
      )}
    </div>
  );
}