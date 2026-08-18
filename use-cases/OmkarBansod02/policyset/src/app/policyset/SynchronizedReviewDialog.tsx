"use client";

import type { ReactNode } from "react";
import {
  ArrowRight,
  ArrowRightLeft,
  CircleCheck,
  Minus,
  TriangleAlert,
} from "lucide-react";
import {
  POLICY_DOCUMENT_TYPES,
  type ChangeSet,
  type ManagedFieldPath,
  type PolicyDocumentType,
} from "@/domain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { DOCUMENT_ICONS, DOCUMENT_TITLES } from "./document-meta";
import { ProposalCard } from "./ProposalDiff";
import { Spinner } from "./shell";
import type { SynchronizedState } from "./workspace-state";

const MANAGED_FIELD_LABELS: Partial<Record<ManagedFieldPath, string>> = {
  "returns.windowDays": "Return window",
  "warranty.durationMonths": "Warranty duration",
};

const MANAGED_FIELD_UNITS: Partial<Record<ManagedFieldPath, string>> = {
  "returns.windowDays": "days",
  "warranty.durationMonths": "months",
};

/**
 * The synchronized ChangeSet review — the product's defining moment. One
 * canonical fact changed; this surface shows which documents PolicySet
 * determined must change together, and approves or rejects them as a set.
 */
export function SynchronizedReviewDialog({
  state,
  onApprove,
  onReject,
  onDismiss,
}: {
  state: SynchronizedState;
  onApprove: () => void;
  onReject: () => void;
  onDismiss: () => void;
}) {
  const changeSet = "changeSet" in state ? state.changeSet : null;
  const open = changeSet !== null;
  const dismissable =
    state.stage === "synchronized" ||
    state.stage === "rejected" ||
    state.stage === "failed";

  if (!changeSet) {
    return null;
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && dismissable) {
          onDismiss();
        }
      }}
    >
      <DialogContent
        showClose={dismissable}
        className="max-w-3xl"
        onEscapeKeyDown={(event) => {
          if (!dismissable) event.preventDefault();
        }}
        onPointerDownOutside={(event) => event.preventDefault()}
        onInteractOutside={(event) => event.preventDefault()}
      >
        <header className="shrink-0 border-b border-line px-6 py-5">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent-ink">
            <ArrowRightLeft className="size-3" />
            Synchronized change
          </p>
          <DialogTitle className="mt-2 text-lg">
            Review synchronized change
          </DialogTitle>
          <DialogDescription className="mt-1 max-w-xl">
            One canonical fact changed. PolicySet determined which documents
            state it, and they are approved or rejected together.
          </DialogDescription>
          <FactDelta changeSet={changeSet} />
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <DialogBody state={state} />
        </div>

        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-line bg-canvas/60 px-6 py-4">
          <DialogFooterContent
            state={state}
            onApprove={onApprove}
            onReject={onReject}
            onDismiss={onDismiss}
          />
        </footer>
      </DialogContent>
    </Dialog>
  );
}

function FactDelta({ changeSet }: { changeSet: ChangeSet }) {
  return (
    <div className="mt-4 rounded-[var(--radius-card)] border border-line bg-canvas px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-faint">
        {MANAGED_FIELD_LABELS[changeSet.fieldPath] ?? changeSet.fieldPath}
      </p>
      <p className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[15px] text-muted line-through decoration-faint">
          {formatValue(changeSet.fieldPath, changeSet.previousValue)}
        </span>
        <ArrowRight className="size-3.5 shrink-0 self-center text-faint" />
        <span className="text-[19px] font-semibold tracking-tight text-ink tabular-nums">
          {formatValue(changeSet.fieldPath, changeSet.nextValue)}
        </span>
      </p>
    </div>
  );
}

function DialogBody({ state }: { state: SynchronizedState }) {
  if (state.stage === "preparing") {
    return (
      <Waiting message="Capturing the authoritative four-document state…" />
    );
  }

  if (state.stage === "processing") {
    return (
      <section>
        <SectionLabel>Drafting</SectionLabel>
        <ul className="space-y-1.5">
          {state.jobs.map((targeted) => (
            <li
              key={targeted.documentType}
              className="flex items-center gap-2.5 rounded-[var(--radius-control)] border border-line bg-surface px-3.5 py-2.5"
            >
              <DocumentIcon documentType={targeted.documentType} />
              <span className="flex-1 text-[13px] font-medium text-ink">
                {DOCUMENT_TITLES[targeted.documentType]}
              </span>
              <span className="flex items-center gap-2 text-xs tabular-nums text-muted">
                {targeted.job.progress === null
                  ? "Preparing…"
                  : `${targeted.job.progress}%`}
                <Spinner className="size-3.5" />
              </span>
            </li>
          ))}
        </ul>
      </section>
    );
  }

  if (state.stage === "applying") {
    return <Waiting message={state.message} />;
  }

  if (state.stage === "synchronized") {
    return (
      <Outcome
        tone="ok"
        title="Synchronized"
        message={`Every document that states this fact now matches the canonical profile.`}
      >
        <ul className="mt-4 space-y-1.5">
          {state.changeSet.affectedDocuments.map((documentType) => (
            <OutcomeRow
              key={documentType}
              documentType={documentType}
              detail="Updated"
              tone="ok"
            />
          ))}
          {state.unchangedDocuments.map((documentType) => (
            <OutcomeRow
              key={documentType}
              documentType={documentType}
              detail="Unchanged"
            />
          ))}
        </ul>
      </Outcome>
    );
  }

  if (state.stage === "rejected") {
    return <Outcome tone="neutral" title="Update rejected" message={state.message} />;
  }

  if (state.stage === "failed") {
    return (
      <Outcome
        tone="danger"
        title="Synchronized update blocked"
        message={state.message}
      >
        <p className="mt-3 text-[13px] leading-relaxed text-muted">
          Nothing was committed to the canonical profile. Review the proposal
          scope and document consistency before trying again.
        </p>
      </Outcome>
    );
  }

  if (state.stage !== "awaiting_review") {
    return null;
  }

  const affected = new Set(state.changeSet.affectedDocuments);
  const untouched = POLICY_DOCUMENT_TYPES.filter(
    (documentType) => !affected.has(documentType),
  );

  return (
    <div className="space-y-6">
      <section>
        <SectionLabel>
          Affected policies · {state.changeSet.affectedDocuments.length}
        </SectionLabel>
        <div className="space-y-5">
          {state.changeSet.affectedDocuments.map((documentType) => {
            const proposals =
              state.jobs.find(
                (targeted) => targeted.documentType === documentType,
              )?.job.proposals ?? [];

            return (
              <section key={documentType}>
                <div className="mb-2 flex items-center gap-2.5">
                  <DocumentIcon documentType={documentType} />
                  <h3 className="text-[13px] font-semibold text-ink">
                    {DOCUMENT_TITLES[documentType]}
                  </h3>
                  <Badge tone="accent">
                    {formatValue(
                      state.changeSet.fieldPath,
                      state.changeSet.previousValue,
                    )}
                    <ArrowRight />
                    {formatValue(
                      state.changeSet.fieldPath,
                      state.changeSet.nextValue,
                    )}
                  </Badge>
                </div>
                <div className="space-y-2.5">
                  {proposals.map((proposal, index) => (
                    <ProposalCard
                      key={proposal.changeId}
                      proposal={proposal}
                      index={index}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </section>

      {untouched.length > 0 ? (
        <section>
          <SectionLabel>Not affected</SectionLabel>
          <ul className="space-y-1.5">
            {untouched.map((documentType) => (
              <OutcomeRow
                key={documentType}
                documentType={documentType}
                detail="Unchanged"
              />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function DialogFooterContent({
  state,
  onApprove,
  onReject,
  onDismiss,
}: {
  state: SynchronizedState;
  onApprove: () => void;
  onReject: () => void;
  onDismiss: () => void;
}) {
  if (state.stage === "awaiting_review") {
    return (
      <>
        <p className="text-xs text-muted">
          Nothing is committed to the canonical profile until you approve.
        </p>
        <div className="ml-auto flex gap-2">
          <Button variant="secondary" onClick={onReject}>
            Reject update
          </Button>
          <Button variant="primary" onClick={onApprove}>
            Approve synchronized update
          </Button>
        </div>
      </>
    );
  }

  if (
    state.stage === "synchronized" ||
    state.stage === "rejected" ||
    state.stage === "failed"
  ) {
    return (
      <Button variant="secondary" className="ml-auto" onClick={onDismiss}>
        Close
      </Button>
    );
  }

  return (
    <p className="text-xs text-muted">
      This can take a moment. Documents are edited through SuperDocs.
    </p>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.09em] text-faint">
      {children}
    </h3>
  );
}

function DocumentIcon({ documentType }: { documentType: PolicyDocumentType }) {
  const Icon = DOCUMENT_ICONS[documentType];
  return <Icon className="size-4 shrink-0 text-faint" />;
}

function OutcomeRow({
  documentType,
  detail,
  tone = "neutral",
}: {
  documentType: PolicyDocumentType;
  detail: string;
  tone?: "neutral" | "ok";
}) {
  return (
    <li className="flex items-center gap-2.5 rounded-[var(--radius-control)] border border-line bg-surface px-3.5 py-2.5">
      <DocumentIcon documentType={documentType} />
      <span className="flex-1 text-[13px] text-ink-soft">
        {DOCUMENT_TITLES[documentType]}
      </span>
      <span
        className={cn(
          "flex items-center gap-1.5 text-xs font-medium",
          tone === "ok" ? "text-ok" : "text-faint",
        )}
      >
        {tone === "ok" ? (
          <CircleCheck className="size-3.5" />
        ) : (
          <Minus className="size-3.5" />
        )}
        {detail}
      </span>
    </li>
  );
}

function Waiting({ message }: { message: string }) {
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2.5 py-10 text-[13px] text-muted"
    >
      <Spinner />
      {message}
    </div>
  );
}

function Outcome({
  tone,
  title,
  message,
  children,
}: {
  tone: "ok" | "danger" | "neutral";
  title: string;
  message: string;
  children?: ReactNode;
}) {
  return (
    <div role={tone === "danger" ? "alert" : "status"}>
      <p
        className={cn(
          "flex items-center gap-2 text-[13px] font-semibold",
          tone === "ok" && "text-ok",
          tone === "danger" && "text-danger",
          tone === "neutral" && "text-ink",
        )}
      >
        {tone === "ok" ? <CircleCheck className="size-4" /> : null}
        {tone === "danger" ? <TriangleAlert className="size-4" /> : null}
        {title}
      </p>
      <p className="mt-1.5 text-[13px] leading-relaxed text-ink-soft">
        {message}
      </p>
      {children}
    </div>
  );
}

function formatValue(fieldPath: ManagedFieldPath, value: unknown): string {
  const unit = MANAGED_FIELD_UNITS[fieldPath];
  return unit ? `${String(value)} ${unit}` : String(value);
}
