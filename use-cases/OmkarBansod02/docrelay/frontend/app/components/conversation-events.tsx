"use client";

import { useState, type ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type {
  ConflictChoice,
  DryRunView,
  FrozenPreviewBlock,
  ProposalView,
  RunView,
  WriteBackView,
} from "../lib/api";
import {
  contextualChange,
  normalizedSafetyChecks,
  processingStepsFromRunState,
  truncateRevision,
  type PersistedWorkflowEvent,
  type ProcessingStepState,
  type VerifiedWriteEvidence,
} from "../lib/conversation";
import { canWriteBack, conflictActions, isVerifiedWriteSuccess } from "../lib/write-back-state";
import {
  attentionMessage,
  humanDryRunFailure,
  safetyFailureRecovery,
} from "../lib/workspace-state";
import { ICON_STROKE, icons } from "@/lib/icons";
import { DocRelayAvatar } from "./brand";
import { extractText } from "./diff-view";
import { MotionFade } from "./motion-panel";

/**
 * Conversation-native presentation of workflow state.
 *
 * These adapters render the SAME underlying workflow data as the full-page
 * workflow screens, but constrained to the conversation column so nothing
 * overflows into the document pane. They never assume desktop grid widths.
 *
 * Only genuinely structured moments — review, safety, write, verified, error —
 * get a surface. Ordinary assistant prose is carried by type and whitespace.
 */

/** Shared structured surface for the few events that need one. */
function EventCard({
  children,
  className,
  tone = "default",
}: {
  children: ReactNode;
  className?: string;
  tone?: "default" | "approved" | "rejected";
}) {
  return (
    <div
      className={cn(
        "min-w-0 max-w-full rounded-[var(--radius-card)] border",
        "transition-[background-color,border-color,box-shadow] duration-[var(--motion-duration)] ease-[var(--motion-ease)]",
        // Structure and tone, not elevation: an event surface sits on the
        // conversation, it does not float above it.
        tone === "approved"
          ? "border-primary-line bg-surface shadow-[var(--shadow-subtle)]"
          : tone === "rejected"
            ? "border-border-light bg-surface-sunken shadow-none"
            : "border-border-light bg-surface shadow-[var(--shadow-subtle)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * One turn frame for both speakers.
 *
 * The avatar column sets a single left edge for the whole thread, so a user
 * instruction and DocRelay's answer to it read as one exchange rather than as
 * two unrelated blocks. Body content starts at the speaker name's x.
 */
export function TurnFrame({
  avatar,
  speaker,
  meta,
  label,
  children,
}: {
  avatar: ReactNode;
  speaker: string;
  meta?: ReactNode;
  label?: string;
  children: ReactNode;
}) {
  return (
    <article
      className="grid min-w-0 grid-cols-[28px_minmax(0,1fr)] gap-x-3"
      aria-label={label ?? speaker}
    >
      <div className="col-start-1 row-start-1 self-start">{avatar}</div>
      <div className="col-start-2 row-start-1 flex min-w-0 items-center gap-2 self-center">
        <p className="type-speaker truncate">{speaker}</p>
        {meta}
      </div>
      <div className="col-start-2 row-start-2 mt-2 min-w-0">{children}</div>
    </article>
  );
}

/**
 * Ongoing-work indicator: three dots that are always laid out and only change
 * opacity, so nothing shifts when the work finishes. Used only where the
 * application really is waiting on something.
 */
export function LiveDots({ label = "In progress" }: { label?: string }) {
  return (
    <>
      <span className="live-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className="sr-only">{label}</span>
    </>
  );
}

export function DocRelayEvent({
  title,
  subtitle,
  mark,
  quiet = false,
  live = false,
  children,
}: {
  title?: string;
  subtitle?: string;
  /** Small glyph before the title, used only for real terminal outcomes. */
  mark?: "verified" | "attention";
  /** Historical, read-only turns recede behind the active run. */
  quiet?: boolean;
  /** True only while this event is waiting on real asynchronous work. */
  live?: boolean;
  children?: ReactNode;
}) {
  return (
    <MotionFade>
      <TurnFrame
        label="DocRelay"
        speaker="DocRelay"
        avatar={<DocRelayAvatar className="size-7" tone={quiet ? "soft" : "solid"} />}
        meta={
          mark === "verified" ? (
            <span className="pill pill-accent">
              <icons.check className="size-3" strokeWidth={2.5} aria-hidden="true" />
              Verified
            </span>
          ) : mark === "attention" ? (
            <span className="pill pill-warning">
              <icons.warning className="size-3" strokeWidth={ICON_STROKE} aria-hidden="true" />
              Attention
            </span>
          ) : undefined
        }
      >
        {title ? (
          <p
            className={cn(
              "type-message min-w-0",
              quiet ? "font-normal text-muted" : "font-medium text-foreground",
            )}
            aria-live={live ? "polite" : undefined}
          >
            {title}
            {live ? <LiveDots /> : null}
          </p>
        ) : null}
        {subtitle ? (
          <p className="type-message mt-1 text-muted">{subtitle}</p>
        ) : null}
        {children ? (
          <div className={cn("min-w-0", title || subtitle ? "mt-3.5" : "")}>{children}</div>
        ) : null}
      </TurnFrame>
    </MotionFade>
  );
}

/**
 * A step's mark on the progress rail.
 *
 * The active step breathes rather than blinks: one slow opacity cycle on a
 * halo that is already there, so nothing appears or disappears mid-run.
 */
function StepMark({ state }: { state: ProcessingStepState }) {
  if (state === "complete") {
    return (
      <span
        className="relative z-1 grid size-[18px] shrink-0 place-items-center rounded-full border border-primary-line bg-accent-soft text-primary"
        aria-hidden="true"
      >
        <icons.check className="size-2.5" strokeWidth={2.75} />
      </span>
    );
  }
  if (state === "current") {
    return (
      <span
        className="relative z-1 grid size-[18px] shrink-0 place-items-center rounded-full border border-primary-line bg-surface"
        aria-hidden="true"
      >
        <span className="absolute inset-0 rounded-full bg-primary/12 live-dot" />
        <span className="size-[7px] rounded-full bg-primary" />
      </span>
    );
  }
  return (
    <span
      className="relative z-1 grid size-[18px] shrink-0 place-items-center rounded-full border border-border-light bg-surface"
      aria-hidden="true"
    >
      <span className="size-[6px] rounded-full bg-border" />
    </span>
  );
}

export function ProcessingEvent({
  run,
  onCheckStatus,
}: {
  run: RunView;
  onCheckStatus?: () => Promise<void>;
}) {
  const [checking, setChecking] = useState(false);
  const reduce = useReducedMotion();

  if (run.provider_read_error) {
    return (
      <DocRelayEvent
        title="Still checking the edit status."
        subtitle="Your document has not been written."
      >
        {onCheckStatus ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={checking}
            onClick={() => {
              setChecking(true);
              void onCheckStatus().finally(() => setChecking(false));
            }}
          >
            {checking ? (
              <icons.refresh className="size-3.5 animate-spin" strokeWidth={ICON_STROKE} />
            ) : null}
            {checking ? "Checking…" : "Check status again"}
          </Button>
        ) : null}
      </DocRelayEvent>
    );
  }

  const steps = processingStepsFromRunState(run.state);
  const attention = attentionMessage(run.attention_code);

  return (
    <DocRelayEvent title="Preparing changes" live>
      {/* A rail rather than a list of bullets: the run reads as one continuous
          process, and a completed step visibly leads into the next. */}
      <ol className="relative" aria-label="Progress" aria-live="polite">
        {steps.map((step, index) => (
          <motion.li
            key={step.label}
            className="relative flex items-center gap-3 pb-3.5 last:pb-0"
            initial={false}
            animate={{ opacity: step.state === "idle" ? 0.55 : 1 }}
            transition={{ duration: reduce ? 0 : 0.2, ease: [0.2, 0.8, 0.2, 1] }}
          >
            {index < steps.length - 1 ? (
              <span
                className={cn(
                  "absolute top-[18px] bottom-0 left-[8.5px] w-px",
                  step.state === "complete" ? "bg-primary-line" : "bg-border-light",
                )}
                aria-hidden="true"
              />
            ) : null}
            <StepMark state={step.state} />
            <span
              className={cn(
                "text-[13.5px] leading-5",
                step.state === "current" ? "font-medium text-foreground" : "text-muted",
              )}
              aria-current={step.state === "current" ? "step" : undefined}
            >
              {step.label}
              {step.state === "current" ? <LiveDots label="in progress" /> : null}
              {step.state === "complete" ? (
                <span className="sr-only"> complete</span>
              ) : null}
            </span>
          </motion.li>
        ))}
      </ol>
      {attention ? (
        <p className="mt-3 text-[13.25px] leading-[1.55] text-warning">
          {attention}
        </p>
      ) : null}
    </DocRelayEvent>
  );
}

/** Compact evidence line used by the safety receipt and the verified event. */
function EvidenceLine({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-[13.25px] leading-[1.55] text-muted">
      <icons.check
        className="size-3.5 shrink-0 translate-y-[3px] text-success"
        strokeWidth={2.5}
        aria-hidden="true"
      />
      <span className="min-w-0">{children}</span>
    </li>
  );
}

/**
 * One side of the change, on its own tinted plate.
 *
 * The plate carries the direction (removed / added); only the exact mutated
 * span inside it is strongly coloured, so the untouched context around the
 * change stays readable and the eye lands on what actually differs.
 */
function ContextualLine({
  label,
  text,
  highlight,
  tone,
  faded,
}: {
  label: string;
  text: string;
  highlight: [number, number] | null;
  tone: "removed" | "added";
  faded: boolean;
}) {
  const removed = tone === "removed";
  return (
    <div
      className={cn(
        "diff-band min-w-0",
        removed ? "diff-band-removed" : "diff-band-added",
        faded ? "opacity-60" : "",
      )}
    >
      <p
        className={cn(
          "flex items-center gap-1.5 text-[11.5px] leading-4 font-medium tracking-[0.045em] uppercase",
          removed ? "text-diff-removed-text" : "text-diff-added-text",
        )}
      >
        <span aria-hidden="true" className="text-[13px] leading-none font-semibold">
          {removed ? "−" : "+"}
        </span>
        {label}
      </p>
      <p className="mt-1.5 min-w-0 break-words text-[13.5px] leading-[1.66] text-foreground">
        {highlight ? (
          <>
            {text.slice(0, highlight[0])}
            <mark className={removed ? "diff-token-removed" : "diff-token-added"}>
              {text.slice(highlight[0], highlight[1])}
            </mark>
            {text.slice(highlight[1])}
          </>
        ) : (
          text
        )}
      </p>
    </div>
  );
}

/** The step between the two plates: direction, not decoration. */
function DiffTransition() {
  return (
    <div className="relative flex h-4 items-center justify-center" aria-hidden="true">
      <span
        className="grid size-[18px] place-items-center rounded-full border border-border-light bg-surface text-muted-soft"
      >
        <svg viewBox="0 0 12 12" className="size-2.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 2v8M3 7l3 3 3-3" />
        </svg>
      </span>
    </div>
  );
}

function ReviewProposalCard({
  proposal,
  index,
  blocks,
  decided,
  approved,
  locked,
  onDecide,
}: {
  proposal: ProposalView;
  index: number;
  blocks: FrozenPreviewBlock[] | null;
  decided: boolean;
  approved: boolean;
  locked: boolean;
  onDecide: (proposalId: string, approve: boolean) => void;
}) {
  const oldText = extractText(proposal.old_html);
  const newText = extractText(proposal.new_html);
  const context = contextualChange(blocks, oldText, newText);
  const rejected = decided && !approved;

  return (
    <EventCard tone={decided ? (approved ? "approved" : "rejected") : "default"}>
      {/* Header band: what this change is, and where it stands. */}
      <div className="flex items-center justify-between gap-2 border-b border-border-hair px-4 py-3">
        <p className="min-w-0 truncate text-[13px] leading-4">
          <span className="font-medium tracking-[-0.01em] text-foreground">
            Proposed change {index + 1}
          </span>
          {context?.heading ? (
            <span className="text-muted"> · {context.heading}</span>
          ) : null}
        </p>
        {/* Only a real decision earns a chip here. "Awaiting review" is already
            said once, by the event this card sits inside. */}
        {decided ? (
          <span className={cn("pill shrink-0", approved ? "pill-accent" : "pill-neutral")}>
            {approved ? (
              <icons.check className="size-3" strokeWidth={2.5} aria-hidden="true" />
            ) : null}
            {approved ? "Approved" : "Rejected"}
          </span>
        ) : null}
      </div>

      <div className="px-4 py-4">
        {context ? (
          <div className="min-w-0">
            <ContextualLine
              label="Removed"
              text={context.beforeText}
              highlight={context.beforeHighlight}
              tone="removed"
              faded={rejected}
            />
            <DiffTransition />
            <ContextualLine
              label="Added"
              text={context.afterText}
              highlight={context.afterHighlight}
              tone="added"
              faded={rejected}
            />
          </div>
        ) : (
          <p className="text-[13.25px] text-muted italic">
            No text content is available for this change.
          </p>
        )}

        {context?.contextual ? (
          <p className="mt-3.5 text-[12.25px] leading-[1.55] text-muted">
            Shown in the surrounding sentence from the frozen document. Only the highlighted span
            changes.
          </p>
        ) : null}

        {!locked ? (
          <div className="mt-4 flex gap-2">
            <Button
              type="button"
              variant={decided && approved ? "default" : "outline"}
              size="sm"
              className="flex-1"
              aria-pressed={decided && approved}
              onClick={() => onDecide(proposal.proposal_id, true)}
            >
              <icons.check
                className={cn("size-3.5", decided && approved ? "" : "text-primary")}
                strokeWidth={2.5}
                aria-hidden="true"
              />
              {decided && approved ? "Approved" : "Approve"}
            </Button>
            <Button
              type="button"
              variant={rejected ? "destructive" : "ghost"}
              size="sm"
              className={cn("flex-1", rejected ? "" : "text-muted hover:text-foreground")}
              aria-pressed={rejected}
              onClick={() => onDecide(proposal.proposal_id, false)}
            >
              {rejected ? "Rejected" : "Reject"}
            </Button>
          </div>
        ) : (
          <p className="mt-4 text-[12.25px] text-muted">Decision recorded</p>
        )}
      </div>
    </EventCard>
  );
}

export function ReviewEvent({
  proposals,
  blocks,
  decisions,
  submitting,
  onDecide,
  onSubmitAll,
}: {
  proposals: ProposalView[];
  blocks?: FrozenPreviewBlock[] | null;
  decisions: Map<string, { approve: boolean; feedback?: string }>;
  submitting: boolean;
  onDecide: (proposalId: string, approve: boolean) => void;
  onSubmitAll: () => void;
}) {
  const count = proposals.length;
  const allDecided = proposals.every(
    (proposal) => decisions.has(proposal.proposal_id) || proposal.decision !== null,
  );
  const hasAnyNew = proposals.some((proposal) => decisions.has(proposal.proposal_id));
  const approvedCount = proposals.filter((proposal) => (
    decisions.get(proposal.proposal_id)?.approve ?? proposal.decision === "APPROVE"
  )).length;
  const decidedCount = proposals.filter((proposal) => (
    decisions.has(proposal.proposal_id) || proposal.decision !== null
  )).length;
  const rejectedCount = decidedCount - approvedCount;

  return (
    <DocRelayEvent
      title={`${count} ${count === 1 ? "change" : "changes"} prepared for review`}
      subtitle="Review each change and approve only what you want to apply."
    >
      <div className="space-y-3.5">
        {proposals.map((proposal, index) => {
          const pending = decisions.get(proposal.proposal_id);
          const existing = proposal.decision;
          const decided = pending !== undefined || existing !== null;
          const approved = pending?.approve ?? existing === "APPROVE";
          return (
            <ReviewProposalCard
              key={proposal.proposal_id}
              proposal={proposal}
              index={index}
              blocks={blocks ?? null}
              decided={decided}
              approved={approved}
              locked={existing !== null}
              onDecide={onDecide}
            />
          );
        })}
      </div>

      <div className="mt-4">
        <Button
          type="button"
          size="lg"
          className="w-full"
          disabled={!allDecided || !hasAnyNew || submitting}
          onClick={onSubmitAll}
        >
          {submitting ? (
            <icons.refresh className="size-3.5 animate-spin" strokeWidth={ICON_STROKE} />
          ) : null}
          {approvedCount === 0
            ? "Continue with no approved changes"
            : `Continue with ${approvedCount} approved ${approvedCount === 1 ? "change" : "changes"}`}
        </Button>
        <p className="mt-2.5 text-center text-[12.25px] leading-4 text-muted">
          {decidedCount === 0
            ? `${count} ${count === 1 ? "change" : "changes"} awaiting your decision`
            : decidedCount < count
              ? `${count - decidedCount} of ${count} still awaiting your decision`
              : rejectedCount > 0
                ? `${approvedCount} approved · ${rejectedCount} rejected`
                : `${approvedCount} approved`}
        </p>
      </div>
    </DocRelayEvent>
  );
}

function mappedChanges(dryRun: DryRunView) {
  if (dryRun.changes && dryRun.changes.length > 0) return dryRun.changes;
  return [{ proposal_id: dryRun.proposal_id, old_text: dryRun.old_text, new_text: dryRun.new_text }];
}

/**
 * Concise safety receipt. Every line is either evidence the dry run reported
 * in `why_safe`, or a fact about the plan that was actually mapped.
 */
export function DryRunEvent({
  dryRun,
  writing,
  onWrite,
}: {
  dryRun: DryRunView;
  writing: boolean;
  onWrite: () => void;
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const count = mappedChanges(dryRun).length;
  const changeWord = count === 1 ? "change" : "changes";

  if (writing) {
    return (
      <DocRelayEvent title="Writing back safely" live>
        <div className="flex items-start gap-2.5 rounded-[10px] border border-border-light bg-surface px-3.5 py-3">
          <span className="relative mt-[3px] grid size-3.5 shrink-0 place-items-center" aria-hidden="true">
            <span className="absolute inset-0 rounded-full bg-primary/15 live-dot" />
            <span className="size-[7px] rounded-full bg-primary" />
          </span>
          <p className="min-w-0 text-[13.5px] leading-[1.6] text-muted" aria-live="polite">
            Creating the backup, writing {count === 1 ? "the approved change" : `the ${count} approved changes`},
            then verifying the result. DocRelay reports only a verified outcome.
          </p>
        </div>
      </DocRelayEvent>
    );
  }

  const revision = dryRun.source?.baseline_revision_id ?? null;

  return (
    <DocRelayEvent
      title="Ready for safe write-back"
      subtitle="No cloud write has happened yet."
    >
      {/* The proof ledger gets a surface of its own: it is the evidence the
          write-back decision rests on, not a caption under it. */}
      <EventCard>
        <div className="flex items-center gap-2 border-b border-border-hair px-4 py-3">
          <icons.shield className="size-3.5 shrink-0 text-primary" strokeWidth={ICON_STROKE} aria-hidden="true" />
          <p className="min-w-0 flex-1 truncate text-[13px] leading-4 font-medium tracking-[-0.01em] text-foreground">
            Safety check
          </p>
          <span className="pill pill-neutral shrink-0">Dry run</span>
        </div>
        <ul className="space-y-2 px-4 py-3.5" aria-label="Safety evidence">
          <EvidenceLine>
            {count} approved {changeWord} mapped to {dryRun.operation_count}{" "}
            guarded {dryRun.operation_count === 1 ? "operation" : "operations"}
          </EvidenceLine>
          {normalizedSafetyChecks(dryRun.why_safe).map((check) => (
            <EvidenceLine key={check}>{check}</EvidenceLine>
          ))}
          {revision ? (
            <EvidenceLine>
              Guarded against source revision{" "}
              <span className="type-mono text-[11.5px]">{truncateRevision(revision)}</span>
            </EvidenceLine>
          ) : null}
        </ul>
      </EventCard>

      <Button
        type="button"
        size="lg"
        className="mt-4 w-full"
        disabled={!canWriteBack(dryRun.status, writing)}
        onClick={onWrite}
      >
        <icons.check className="size-3.5" strokeWidth={2.5} aria-hidden="true" />
        Approve and write back
      </Button>

      {dryRun.mapping_proof_id || dryRun.write_plan_id ? (
        <div className="mt-2.5">
          <button
            type="button"
            aria-expanded={showEvidence}
            onClick={() => setShowEvidence((value) => !value)}
            className="inline-flex items-center gap-1 text-[12.25px] text-muted transition-colors duration-[var(--motion-duration)] hover:text-foreground"
          >
            Technical evidence
            <icons.chevronDown
              className={cn(
                "size-3.5 transition-transform duration-[var(--motion-duration)] ease-[var(--motion-ease)]",
                showEvidence ? "rotate-180" : "",
              )}
              strokeWidth={ICON_STROKE}
              aria-hidden="true"
            />
          </button>
          {showEvidence ? (
            <dl className="mt-2 space-y-2 rounded-[10px] border border-border-light bg-surface px-3 py-2.5 font-mono text-[11.5px] leading-[1.5] text-muted">
              {dryRun.mapping_proof_id ? (
                <EvidenceRow label="MappingProof" value={dryRun.mapping_proof_id} />
              ) : null}
              {dryRun.write_plan_id ? (
                <EvidenceRow label="WritePlan" value={dryRun.write_plan_id} />
              ) : null}
              {dryRun.write_plan_sha256 ? (
                <EvidenceRow label="Plan SHA-256" value={dryRun.write_plan_sha256} />
              ) : null}
              <EvidenceRow label="cloud_mutation_performed" value="false" />
            </dl>
          ) : null}
        </div>
      ) : null}
    </DocRelayEvent>
  );
}

function EvidenceRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid min-w-0 gap-0.5">
      <dt>{label}</dt>
      <dd className="break-all text-foreground">{value}</dd>
    </div>
  );
}

export function VerifiedWriteEvent({
  evidence,
}: {
  evidence: VerifiedWriteEvidence;
}) {
  const driveUrl = `https://docs.google.com/document/d/${encodeURIComponent(evidence.fileId)}/edit`;
  const checks = [
    evidence.backupCreated ? "Backup created" : null,
    evidence.writeApplied ? "Google write completed" : null,
    evidence.structurallyVerified ? "Result verified" : null,
  ].filter((item): item is string => item !== null);

  return (
    <DocRelayEvent
      mark="verified"
      title="Change written and verified."
      subtitle="The approved change is now in Google Drive."
    >
      {checks.length > 0 ? (
        <EventCard tone="approved">
          <ul className="space-y-2 px-4 py-3.5" aria-label="Verified write evidence">
            {checks.map((check) => (
              <EvidenceLine key={check}>{check}</EvidenceLine>
            ))}
          </ul>
        </EventCard>
      ) : null}
      <Button type="button" variant="outline" size="sm" className="mt-3.5" asChild>
        <a href={driveUrl} target="_blank" rel="noreferrer">
          <icons.externalLink data-icon="inline-start" strokeWidth={ICON_STROKE} />
          Open in Google Drive
        </a>
      </Button>
    </DocRelayEvent>
  );
}

/** Read-only event projected from durable run summary fields. */
export function PersistedRunEvent({ event }: { event: PersistedWorkflowEvent }) {
  if (event.kind === "verified") {
    return <DocRelayEvent quiet mark="verified" title="Change written and verified." />;
  }
  if (event.kind === "review") {
    return (
      <DocRelayEvent
        quiet
        title={`${event.changeCount} ${event.changeCount === 1 ? "change" : "changes"} prepared for review`}
        subtitle="This is a historical workflow state."
      />
    );
  }
  if (event.kind === "ready") {
    const count = event.changeCount;
    return (
      <DocRelayEvent
        quiet
        title={count > 0
          ? `${count} ${count === 1 ? "change" : "changes"} ready`
          : "Changes ready for the next workflow step"}
        subtitle="No verified write is recorded for this run."
      />
    );
  }
  if (event.kind === "conflict") {
    return (
      <DocRelayEvent
        quiet
        mark="attention"
        title="Document changed while this edit was in progress."
        subtitle="DocRelay did not record a verified write for this run."
      />
    );
  }
  if (event.kind === "attention") {
    return (
      <DocRelayEvent
        quiet
        mark="attention"
        title="This run needs attention."
        subtitle={event.code ? event.code.replace(/_/g, " ").toLowerCase() : "Its outcome is not safely verified."}
      />
    );
  }

  const copy = {
    unsupported: ["This change could not be safely written.", "No verified write is recorded."],
    failed: ["This change did not complete safely.", "No verified write is recorded."],
    cancelled: ["This change was cancelled.", "No verified write is recorded."],
    skipped: ["This change was skipped.", "No verified write is recorded."],
    expired: ["This change expired.", "No verified write is recorded."],
    completed: ["Workflow completed.", "No verified Google write is recorded."],
  } as const;
  const [title, subtitle] = copy[event.status];
  return <DocRelayEvent quiet title={title} subtitle={subtitle} />;
}

export function WriteResultEvent({
  fileId,
  result,
  deciding,
  onDecision,
}: {
  fileId: string | null;
  result: WriteBackView;
  deciding: boolean;
  onDecision: (choice: ConflictChoice) => void;
}) {
  if (isVerifiedWriteSuccess(result.status, result.structurally_verified)) {
    return fileId ? (
      <VerifiedWriteEvent
        evidence={{
          runId: result.run_id,
          fileId,
          backupCreated: result.backup_created,
          backupVerified: result.backup_verified,
          writeApplied: result.write_applied,
          structurallyVerified: true,
        }}
      />
    ) : null;
  }

  if (result.status === "CONFLICT" && result.conflict) {
    return (
      <DocRelayEvent
        mark="attention"
        title="Google Drive has a newer version."
        subtitle="DocRelay stopped before applying the change. Nothing was overwritten."
      >
        <div className="flex flex-col gap-2">
          {[...conflictActions].reverse().map((action) => (
            <Button
              key={action.choice}
              type="button"
              size="sm"
              variant={action.choice === "REVIEW_LATEST" ? "default" : "outline"}
              className="w-full"
              disabled={deciding}
              onClick={() => onDecision(action.choice)}
            >
              {action.label}
            </Button>
          ))}
        </div>
      </DocRelayEvent>
    );
  }

  const unknown = result.status === "ATTENTION";
  const title = unknown
    ? "DocRelay cannot prove the external outcome yet."
    : result.status === "IN_PROGRESS"
      ? "The server has already claimed this workflow."
      : result.status === "CANCELLED"
        ? "Write-back was cancelled."
        : "Safe write-back stopped.";
  const subtitle = unknown
    ? "It will not start another write automatically."
    : result.status === "IN_PROGRESS"
      ? "No second write was started."
      : result.status === "CANCELLED"
        ? "No DocRelay change was applied."
        : "The safety pipeline stopped before a verified result was available.";

  return (
    <DocRelayEvent mark="attention" title={title} subtitle={subtitle}>
      {unknown ? (
        <p className="text-[13.5px] leading-[1.6] text-warning">
          Check the document in Google Drive before asking for another change.
        </p>
      ) : null}
      {result.attention_code ? (
        <p className={cn("font-mono text-[11.5px] text-muted", unknown ? "mt-2" : "")}>
          {result.attention_code}
        </p>
      ) : null}
    </DocRelayEvent>
  );
}

export function UnsupportedEvent({
  dryRun,
  onReturn,
}: {
  dryRun: DryRunView;
  onReturn: () => void;
}) {
  const recovery = safetyFailureRecovery(dryRun.reason_code);
  return (
    <DocRelayEvent
      title="This change can't be safely written back."
      subtitle="No cloud changes were made."
    >
      <p className="text-[13.5px] leading-[1.6] text-warning">
        {humanDryRunFailure(dryRun.reason_code, dryRun.reason)}
      </p>
      <Button type="button" variant="outline" size="sm" className="mt-3" onClick={onReturn}>
        {recovery.kind === "refresh-source" ? recovery.label : "Return to document"}
      </Button>
    </DocRelayEvent>
  );
}

export function ConversationErrorEvent({
  message,
  recoverable,
  onRetry,
}: {
  message: string;
  recoverable: boolean;
  onRetry: () => void;
}) {
  return (
    <DocRelayEvent
      mark="attention"
      title={recoverable
        ? "I couldn't finish this step."
        : "This change was not completed safely."}
      subtitle={recoverable
        ? `${message} Your document has not been written.`
        : message}
    >
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
        {recoverable ? "Try again" : "Start over"}
      </Button>
    </DocRelayEvent>
  );
}
