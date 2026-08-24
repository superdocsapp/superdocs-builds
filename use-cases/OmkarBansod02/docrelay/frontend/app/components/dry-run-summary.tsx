"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";
import type { DryRunView, SourceRegistration } from "../lib/api";
import { normalizedSafetyChecks } from "../lib/conversation";
import { canWriteBack } from "../lib/write-back-state";
import { DiffView } from "./diff-view";
import { DocumentIdentity, type DocumentIdentityData, shortId } from "./document-identity";
import { WorkflowProgress } from "./workflow-progress";
import { Button, StateMark } from "./ui";

export function DryRunSummary({
  source,
  document,
  dryRun,
  writing,
  onWrite,
}: {
  source?: SourceRegistration;
  document?: DocumentIdentityData;
  dryRun: DryRunView;
  writing: boolean;
  onWrite: () => void;
}) {
  const [showDetails, setShowDetails] = useState(false);
  const identity = document ?? (source ? { name: source.source.name, revision: source.baseline.revision_id } : { name: "Google document", revision: dryRun.source?.baseline_revision_id ?? null });
  const safetyChecks = normalizedSafetyChecks(dryRun.why_safe);

  return (
    <div>
      <DocumentIdentity document={identity} />
      <WorkflowProgress current="Safety check" />
      <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.72fr)]">
        <section className="px-5 py-9 sm:px-8 lg:px-10 lg:py-10">
          <h2 className="type-page-title">Ready for safe write-back</h2>
          <p className="mt-2 max-w-[680px] text-[15px] leading-6 text-muted">{writePlanSummary(dryRun)}</p>

          <div className="mt-8">
            <h3 className="text-[15.5px] font-semibold tracking-[-0.022em] text-ink">{(dryRun.changes?.length ?? 1) > 1 ? "Changes to write" : "Change to write"}</h3>
            <div className="mt-6 grid gap-8">
              {mappedChanges(dryRun).map((change, index) => (
                <div key={change.proposal_id ?? String(index)}>
                  {mappedChanges(dryRun).length > 1 ? <p className="type-section-heading mb-3">Change {index + 1}</p> : null}
                  <DiffView oldText={change.old_text} newText={change.new_text} context={change.context} compact />
                </div>
              ))}
            </div>
          </div>

          <dl className="surface-section mt-7 divide-y divide-border-hair px-4 text-[14px]">
            {dryRun.structural_location ? <DetailRow label="Location" value={locationSummary(dryRun.structural_location)} /> : null}
            <DetailRow label="Operations" value={String(dryRun.operation_count)} />
            <DetailRow label="Source revision" value={dryRun.source?.baseline_revision_id ? shortId(dryRun.source.baseline_revision_id) : "—"} mono />
          </dl>

          <div className="mt-6 flex items-center gap-2.5 rounded-[var(--radius-card)] border border-primary-line bg-accent-soft px-4 py-3 text-[14.5px] font-medium text-success">
            <span className="grid size-[18px] place-items-center rounded-full border border-primary-line bg-surface text-[11px] text-primary" aria-hidden="true">✓</span>
            No cloud write has happened yet
          </div>

          <Button disabled={!canWriteBack(dryRun.status, writing)} busy={writing} onClick={onWrite} className="mt-6 w-full text-[15px]">
            {writing ? "Creating and verifying backup…" : "Write back safely"}
          </Button>

          <button type="button" onClick={() => setShowDetails((value) => !value)} aria-expanded={showDetails} className="type-button mx-auto mt-3 flex h-8 items-center gap-1.5 rounded-[8px] px-3 text-accent hover:bg-accent-soft">
            View technical evidence
            <ChevronDown className={`size-4 transition-transform ${showDetails ? "rotate-180" : ""}`} aria-hidden="true" />
          </button>
          {showDetails ? <TechnicalDetails dryRun={dryRun} /> : null}

          <p className="mt-5 border-t border-border-hair pt-5 text-[13px] text-muted">DocRelay stops if Google Drive has a newer revision.</p>
        </section>

        <aside className="border-t border-border-light px-5 py-8 sm:px-8 lg:border-t-0 lg:border-l lg:px-8 lg:py-10">
          <h2 className="text-[15.5px] font-semibold tracking-[-0.022em] text-ink">Safety checks</h2>
          <div className="mt-8">
            {safetyChecks.map((label, index) => (
              <div key={label} className="relative flex gap-3 pb-8 last:pb-0">
                {index < safetyChecks.length - 1 ? <span className="absolute top-[18px] bottom-0 left-[8.5px] w-px bg-primary-line" aria-hidden="true" /> : null}
                <StateMark state="complete" />
                <span className="text-[14px] leading-5 text-ink">{label}</span>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}

function TechnicalDetails({ dryRun }: { dryRun: DryRunView }) {
  return (
    <dl className="mt-2 space-y-3 rounded-[var(--radius-card)] border border-border-light bg-surface-sunken p-4 font-mono text-[11px] leading-5 text-muted">
      {dryRun.mapping_proof_id ? <TechnicalRow label="MappingProof" value={dryRun.mapping_proof_id} /> : null}
      {dryRun.mapping_proof_sha256 ? <TechnicalRow label="Proof SHA-256" value={dryRun.mapping_proof_sha256} /> : null}
      {dryRun.write_plan_id ? <TechnicalRow label="WritePlan" value={dryRun.write_plan_id} /> : null}
      {dryRun.write_plan_sha256 ? <TechnicalRow label="Plan SHA-256" value={dryRun.write_plan_sha256} /> : null}
      <TechnicalRow label="cloud_mutation_performed" value="false" />
      {dryRun.provider_operation ? <TechnicalRow label="Provider operation" value={JSON.stringify(dryRun.provider_operation)} /> : null}
    </dl>
  );
}

function DetailRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="grid grid-cols-[150px_1fr] gap-4 py-3"><dt className="text-muted">{label}</dt><dd className={mono ? "font-mono text-[12px] text-ink" : "text-ink"}>{value}</dd></div>;
}

function TechnicalRow({ label, value }: { label: string; value: string }) {
  return <div className="grid gap-1 sm:grid-cols-[150px_1fr]"><dt>{label}</dt><dd className="break-all text-ink/75">{value}</dd></div>;
}

function writePlanSummary(dryRun: DryRunView): string {
  const changeCount = mappedChanges(dryRun).length;
  const operationCount = dryRun.operation_count;
  if (changeCount <= 1) {
    return `The approved change is mapped to ${operationPhrase(operationCount)} guarded Google Docs ${operationCount === 1 ? "operation" : "operations"}.`;
  }
  return `${changeCount} approved changes will be written as ${operationCount} guarded Google Docs operations.`;
}

function mappedChanges(dryRun: DryRunView): Array<{ proposal_id?: string | null; old_text: string | null; new_text: string | null; context?: DryRunView["context"] }> {
  if (dryRun.changes && dryRun.changes.length > 0) return dryRun.changes;
  return [{ proposal_id: dryRun.proposal_id, old_text: dryRun.old_text, new_text: dryRun.new_text, context: dryRun.context }];
}

function locationSummary(location: Record<string, unknown>): string {
  return typeof location.paragraph_index === "number" ? `Paragraph ${location.paragraph_index + 1}` : "Document body";
}

function operationPhrase(count: number): string {
  if (count === 1) return "one";
  if (count === 2) return "two";
  return String(count);
}
