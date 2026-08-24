"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";
import type { ProposalView, SourceRegistration } from "../lib/api";
import { DiffView, extractText } from "./diff-view";
import { DocumentIdentity, type DocumentIdentityData } from "./document-identity";
import { WorkflowProgress } from "./workflow-progress";
import { Button, StateMark } from "./ui";

export function ReviewPanel({
  source,
  document,
  proposals,
  decisions,
  submitting,
  onDecide,
  onSubmitAll,
}: {
  source?: SourceRegistration;
  document?: DocumentIdentityData;
  proposals: ProposalView[];
  decisions: Map<string, { approve: boolean; feedback?: string }>;
  submitting: boolean;
  onDecide: (proposalId: string, approve: boolean) => void;
  onSubmitAll: () => void;
}) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const selected = proposals[Math.min(selectedIndex, Math.max(proposals.length - 1, 0))];
  const allDecided = proposals.every((proposal) => decisions.has(proposal.proposal_id) || proposal.decision !== null);
  const hasAnyNew = proposals.some((proposal) => decisions.has(proposal.proposal_id));
  const identity = document ?? (source ? { name: source.source.name, revision: source.baseline.revision_id } : { name: "Google document", revision: null });

  if (!selected) {
    return (
      <div>
        <DocumentIdentity document={identity} />
        <WorkflowProgress current="Review" />
        <p className="px-5 py-12 text-[14px] text-muted sm:px-8 lg:px-10">No proposals are waiting for review.</p>
      </div>
    );
  }

  const existing = selected.decision;
  const pending = decisions.get(selected.proposal_id);
  const approved = pending?.approve ?? existing === "APPROVE";

  return (
    <div>
      <DocumentIdentity document={identity} />
      <WorkflowProgress current="Review" />
      <div className="grid lg:grid-cols-[minmax(0,1fr)_270px]">
        <section className="min-w-0 px-5 py-9 sm:px-8 lg:px-10 lg:py-10">
          <h2 className="type-page-title">Review proposed changes</h2>
          <p className="mt-2 text-[14px] leading-6 text-muted sm:text-[15px]">Approve or reject every change before DocRelay prepares a write plan.</p>

          <div className="surface-section mt-7 grid overflow-hidden md:grid-cols-[220px_minmax(0,1fr)]">
            <aside className="border-b border-border-light bg-surface-sunken md:border-r md:border-b-0">
              <div className="border-b border-border-hair px-4 py-3.5 text-[13px] font-medium tracking-[-0.01em] text-ink">{proposals.length} proposed {proposals.length === 1 ? "change" : "changes"}</div>
              <div className="hidden md:block">
                {proposals.map((proposal, index) => {
                  const decision = decisions.get(proposal.proposal_id);
                  const isSelected = index === selectedIndex;
                  const resolved = decision !== undefined || proposal.decision !== null;
                  return (
                    <button
                      type="button"
                      key={proposal.proposal_id}
                      onClick={() => setSelectedIndex(index)}
                      className={`flex min-h-[52px] w-full items-center gap-3 border-b border-border-hair px-4 text-left text-[13px] transition-colors duration-[var(--motion-duration)] last:border-b-0 ${isSelected ? "bg-surface font-medium text-ink" : "text-muted hover:bg-surface/70"}`}
                    >
                      <StateMark state={resolved ? "complete" : isSelected ? "current" : "idle"} />
                      <span>{index + 1}</span>
                      <span className="truncate capitalize">{proposal.operation || "Proposed"} change</span>
                    </button>
                  );
                })}
              </div>
              <label className="relative block md:hidden">
                <span className="sr-only">Selected proposal</span>
                <select value={selectedIndex} onChange={(event) => setSelectedIndex(Number(event.target.value))} className="min-h-12 w-full appearance-none bg-surface px-4 pr-10 text-[14px] text-ink outline-none">
                  {proposals.map((proposal, index) => <option key={proposal.proposal_id} value={index}>Change {index + 1} of {proposals.length} · {proposal.operation || "Proposal"}</option>)}
                </select>
                <ChevronDown className="pointer-events-none absolute right-4 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden="true" />
              </label>
            </aside>

            <div className="min-w-0 bg-surface">
              <div className="border-b border-border-hair bg-surface-sunken px-5 py-3.5 text-[13px] font-medium tracking-[-0.01em] text-ink">Proposed change {selectedIndex + 1} of {proposals.length}</div>
              <div className="px-5 py-7 sm:px-7">
                <DiffView oldText={extractText(selected.old_html)} newText={extractText(selected.new_html)} />
                {selected.ai_explanation ? (
                  <div className="mt-8 border-t border-border-hair pt-6">
                    <h3 className="text-[13px] font-semibold text-ink">SuperDocs rationale</h3>
                    <p className="mt-2 text-[14px] leading-6 text-muted">{selected.ai_explanation}</p>
                  </div>
                ) : null}
              </div>

              <div className="sticky bottom-[76px] flex flex-wrap justify-end gap-2.5 border-t border-border-hair bg-surface px-5 py-4 lg:static">
                <Button variant={pending && !pending.approve ? "danger" : "secondary"} disabled={submitting || existing !== null} onClick={() => onDecide(selected.proposal_id, false)} className="min-w-[120px]">Reject</Button>
                <Button disabled={submitting || existing !== null} onClick={() => onDecide(selected.proposal_id, true)} className="min-w-[160px]">{approved ? "Approved" : "Approve change"}</Button>
              </div>
            </div>
          </div>

          <div className="mt-5 flex justify-end">
            <Button busy={submitting} disabled={!allDecided || !hasAnyNew} onClick={onSubmitAll} className="min-w-[180px]">
              Submit {proposals.length} {proposals.length === 1 ? "decision" : "decisions"}
            </Button>
          </div>
        </section>

        <aside className="border-t border-border-light px-5 py-8 sm:px-8 lg:border-t-0 lg:border-l lg:px-7 lg:py-10">
          <h2 className="text-[15px] font-semibold tracking-[-0.022em] text-ink">Review evidence</h2>
          <div className="mt-7">
            {[
              { label: "Proposal received", state: "complete" as const },
              { label: extractText(selected.old_html) ? "Exact old text captured" : "Old text unavailable", state: extractText(selected.old_html) ? "complete" as const : "info" as const },
              { label: existing || pending ? "Decision recorded" : "Decision required", state: existing || pending ? "complete" as const : "current" as const },
            ].map((item, index, items) => (
              <div key={item.label} className="relative flex gap-3 pb-9 last:pb-0">
                {index < items.length - 1 ? <span className="absolute top-[18px] bottom-0 left-[8.5px] w-px bg-border-light" aria-hidden="true" /> : null}
                <StateMark state={item.state} />
                <span className="text-[13px] leading-5 text-ink">{item.label}</span>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
