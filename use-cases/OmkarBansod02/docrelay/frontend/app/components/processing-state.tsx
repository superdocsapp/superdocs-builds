"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
import type { RunView, SourceRegistration } from "../lib/api";
import { humanRunState, attentionMessage } from "../lib/workspace-state";
import { DocumentIdentity } from "./document-identity";
import { WorkflowProgress } from "./workflow-progress";
import { Button, InlineNotice, StateMark } from "./ui";
import type { DocumentIdentityData } from "./document-identity";

export function ProcessingState({
  source,
  document,
  run,
  onCheckStatus,
  embedded = false,
}: {
  source?: SourceRegistration;
  document?: DocumentIdentityData;
  run: RunView;
  onCheckStatus?: () => Promise<void>;
  embedded?: boolean;
}) {
  const [checking, setChecking] = useState(false);
  const attention = attentionMessage(run.attention_code);
  const identity = document ?? (source
    ? { name: source.source.name, revision: source.baseline.revision_id }
    : { name: "Google document", revision: run.provider_revision_id });

  if (run.provider_read_error) {
    return (
      <div>
        {embedded ? null : (
          <>
            <DocumentIdentity document={identity} />
            <WorkflowProgress current="Instruction" warning />
          </>
        )}
        <section className={embedded ? "py-2" : "mx-auto max-w-[760px] px-5 py-14 sm:px-8 lg:py-20"}>
          <h2 className="type-page-title">SuperDocs status is temporarily delayed</h2>
          <div className="mt-6"><InlineNotice tone="info">SuperDocs is taking longer than expected to report this run&apos;s status. No cloud write was made.</InlineNotice></div>
          <p className="mt-5 text-[14px] leading-6 text-muted">The run and its last verified state are saved. Checking again only reads <span className="font-mono text-[12.25px]">jobs.get</span>; it does not repeat the edit request.</p>
          {onCheckStatus ? <Button variant="secondary" className="mt-7" busy={checking} disabled={checking} onClick={() => { setChecking(true); void onCheckStatus().finally(() => setChecking(false)); }}><RefreshCw className="size-4" />{checking ? "Checking status…" : "Check status again"}</Button> : null}
        </section>
      </div>
    );
  }

  return (
    <div>
      {embedded ? null : (
        <>
          <DocumentIdentity document={identity} />
          <WorkflowProgress current="Instruction" />
        </>
      )}
      <section className={embedded ? "py-1" : "mx-auto max-w-[760px] px-5 py-14 sm:px-8 lg:py-20"}>
        <div className="flex items-center gap-4">
          <Loader2 className="size-6 animate-spin text-accent" aria-hidden="true" />
          <div>
            <h2 className={embedded ? "text-[15px] font-semibold tracking-[-0.02em] text-ink" : "type-page-title"}>Preparing your change</h2>
            <p className="mt-1 text-[14px] text-muted">{humanRunState(run.state)}</p>
          </div>
        </div>
        <ol className="mt-10 border-l border-border-light pl-7">
          {processingSteps(run.state).map((step) => (
            <li key={step.label} className="relative flex min-h-16 items-start gap-3">
              <span className="absolute -left-[37px] bg-background"><StateMark state={step.state} /></span>
              <div>
                <p className={`text-[14px] ${step.state === "current" ? "font-medium text-ink" : "text-muted"}`}>{step.label}</p>
                {step.detail ? <p className="mt-1 text-[12.25px] text-muted">{step.detail}</p> : null}
              </div>
            </li>
          ))}
        </ol>
        {attention ? <div className="mt-5"><InlineNotice tone="warning">{attention}</InlineNotice></div> : null}
      </section>
    </div>
  );
}

function processingSteps(state: RunView["state"]): { label: string; detail?: string; state: "idle" | "current" | "complete" }[] {
  const active = state === "QUEUED" ? 0 : state === "BASELINING" ? 1 : 2;
  return [
    { label: "Reading source", detail: "Using the selected immutable Google revision." },
    { label: "Preparing SuperDocs session" },
    { label: "Analyzing instruction" },
    { label: "Preparing proposed change" },
    { label: "Waiting for review" },
  ].map((item, index) => ({ ...item, state: index < active ? "complete" as const : index === active ? "current" as const : "idle" as const }));
}
