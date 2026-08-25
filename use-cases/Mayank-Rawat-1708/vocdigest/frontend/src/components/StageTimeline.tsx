/**
 * @file src/components/StageTimeline.tsx
 * @description The visible-steps surface. Renders all nine stages with per-stage
 *   status, timing and token cost, plus the agent's decision log so a reader can see
 *   not just what ran but what it decided and why.
 * @flow timeline[] + decisions[] -> a vertical list of stage rows, each expandable to
 *   show the decisions recorded during that stage.
 * @dependencies lucide-react icons, clsx
 */
import { useState } from "react";
import clsx from "clsx";
import { CheckCircle2, CircleDashed, Loader2, SkipForward, XCircle, ChevronRight, RotateCw, Forward } from "lucide-react";
import type { DecisionEntry, StageRecord } from "../lib/api";

const ICONS = {
  COMPLETE: <CheckCircle2 className="w-4 h-4 text-emerald-600" />,
  RUNNING: <Loader2 className="w-4 h-4 text-accent animate-spin" />,
  FAILED: <XCircle className="w-4 h-4 text-red-600" />,
  SKIPPED: <SkipForward className="w-4 h-4 text-slate-400" />,
  PENDING: <CircleDashed className="w-4 h-4 text-slate-300" />,
};

const LABELS: Record<string, string> = {
  ingest: "Ingest conversations",
  classify: "Classify & filter",
  extract: "Extract facts",
  theme: "Cluster themes",
  anonymize: "Anonymize quotes",
  compare: "Compare to prior quarter",
  draft: "Draft digest sections",
  human_gate: "Human approval gate",
  superdocs: "SuperDocs edit & export",
};

// Skipping these would either leave nothing to report or publish unreviewed content,
// so the control is not offered. The API refuses them too — this only hides a button
// the user would otherwise get a 409 from.
const UNSKIPPABLE = new Set(["ingest", "theme", "human_gate"]);

export function StageTimeline({
  timeline, decisions, onRetry, onRetryStage, onSkipStage,
}: {
  timeline: StageRecord[];
  decisions: DecisionEntry[];
  onRetry?: () => void;
  onRetryStage?: (stage: string) => void;
  onSkipStage?: (stage: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <ol className="space-y-1">
      {timeline.map((stage) => {
        const stageDecisions = decisions.filter((d) => d.stage === stage.stage);
        const expanded = open === stage.stage;
        return (
          <li key={stage.stage} className="card p-0 overflow-hidden">
            <button
              onClick={() => setOpen(expanded ? null : stage.stage)}
              className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/60 transition"
            >
              {ICONS[stage.status] ?? ICONS.PENDING}
              <span className={clsx("flex-1 text-sm font-medium",
                stage.status === "SKIPPED" && "line-through text-slate-400",
                stage.status === "PENDING" && "text-slate-400")}>
                {LABELS[stage.stage] ?? stage.stage}
              </span>

              {stage.duration_seconds != null && (
                <span className="text-xs text-slate-500 tabular-nums">{stage.duration_seconds.toFixed(1)}s</span>
              )}
              {stage.groq_tokens_used > 0 && (
                <span className="text-xs text-slate-500 tabular-nums">{stage.groq_tokens_used.toLocaleString()} tok</span>
              )}
              {stage.attempts > 1 && (
                <span className="text-xs text-amber-600" title="retried">×{stage.attempts}</span>
              )}
              {stageDecisions.length > 0 && (
                <ChevronRight className={clsx("w-4 h-4 text-slate-400 transition", expanded && "rotate-90")} />
              )}
            </button>

            {stage.status === "FAILED" && (
              <div className="px-4 pb-3 space-y-2">
                <p className="text-xs text-red-600 dark:text-red-400">{stage.error}</p>
                <div className="flex items-center gap-2">
                  {onRetryStage && (
                    <button onClick={() => onRetryStage(stage.stage)} className="btn-ghost text-xs py-1 px-2">
                      <RotateCw className="w-3 h-3" /> Retry this stage
                    </button>
                  )}
                  {onSkipStage && !UNSKIPPABLE.has(stage.stage) && (
                    <button onClick={() => onSkipStage(stage.stage)} className="btn-ghost text-xs py-1 px-2">
                      <Forward className="w-3 h-3" /> Skip
                    </button>
                  )}
                  {onRetry && (
                    <button onClick={onRetry} className="btn-ghost text-xs py-1 px-2">
                      Resume run
                    </button>
                  )}
                </div>
              </div>
            )}

            {stage.status === "COMPLETE" && onRetryStage && (
              <div className="px-4 pb-3">
                <button
                  onClick={() => onRetryStage(stage.stage)}
                  className="text-xs text-slate-400 hover:text-accent transition"
                  title="Re-runs this stage and everything after it"
                >
                  <RotateCw className="w-3 h-3 inline mr-1" />Re-run from here
                </button>
              </div>
            )}

            {expanded && stageDecisions.length > 0 && (
              <div className="px-4 pb-3 pt-1 border-t border-slate-100 dark:border-slate-800 space-y-2">
                {stageDecisions.map((d, i) => (
                  <div key={i} className="text-xs">
                    <span className="font-mono font-semibold text-accent">{d.decision}</span>
                    <span className="text-slate-600 dark:text-slate-400"> — {d.reason}</span>
                  </div>
                ))}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
