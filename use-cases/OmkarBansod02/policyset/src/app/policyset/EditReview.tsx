"use client";

import { CircleCheck, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DOCUMENT_TITLES } from "./document-meta";
import { ProposalCard } from "./ProposalDiff";
import { Spinner } from "./shell";
import type { EditState } from "./workspace-state";

/**
 * Compact progress/result line for the AI command dock. Review itself happens
 * in the inspector, next to the document it changes.
 */
export function EditStatusLine({
  state,
  onDismiss,
}: {
  state: EditState;
  onDismiss: () => void;
}) {
  if (state.stage === "idle" || state.stage === "awaiting_review") {
    return null;
  }

  if (state.stage === "completed" || state.stage === "error") {
    const isError = state.stage === "error";
    return (
      <div
        role={isError ? "alert" : "status"}
        className={cn(
          "flex items-start gap-2 rounded-[var(--radius-control)] border px-3 py-2 text-[13px] leading-relaxed",
          isError
            ? "border-danger-line bg-danger-soft text-danger"
            : "border-ok-line bg-ok-soft text-ok",
        )}
      >
        {isError ? (
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        ) : (
          <CircleCheck className="mt-0.5 size-4 shrink-0" />
        )}
        <span className="min-w-0 flex-1">{state.message}</span>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="-mr-1 rounded p-0.5 opacity-60 transition-opacity duration-150 hover:opacity-100"
        >
          <X className="size-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div
      role="status"
      className="flex items-center gap-2 px-1 text-[13px] text-muted"
    >
      <Spinner className="size-3.5" />
      {state.stage === "submitting" ? "Submitting edit…" : null}
      {state.stage === "processing"
        ? `SuperDocs is preparing proposals${
            state.job.progress === null ? "…" : ` — ${state.job.progress}%`
          }`
        : null}
      {state.stage === "applying" ? state.message : null}
    </div>
  );
}

/** Single-document proposal review, shown in place of Policy facts. */
export function EditReviewPanel({
  state,
  onApprove,
  onReject,
}: {
  state: Extract<EditState, { stage: "awaiting_review" }>;
  onApprove: () => void;
  onReject: () => void;
}) {
  const { job, target } = state;

  return (
    <div className="flex h-full flex-col" aria-label="SuperDocs proposed changes">
      <div className="border-b border-line px-5 py-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-warn">
          Review required
        </p>
        <h2 className="mt-1.5 text-[13px] font-semibold text-ink">
          {DOCUMENT_TITLES[target.documentType]}
        </h2>
        <p className="mt-1 text-xs text-muted">
          {job.proposals.length} proposed{" "}
          {job.proposals.length === 1 ? "change" : "changes"}. Nothing is applied
          until you approve.
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {job.proposals.map((proposal, index) => (
          <ProposalCard
            key={proposal.changeId}
            proposal={proposal}
            index={index}
            layout="stacked"
          />
        ))}
      </div>

      <div className="flex gap-2 border-t border-line bg-surface p-4">
        <Button variant="secondary" className="flex-1" onClick={onReject}>
          Reject
        </Button>
        <Button variant="primary" className="flex-1" onClick={onApprove}>
          Approve
        </Button>
      </div>
    </div>
  );
}
