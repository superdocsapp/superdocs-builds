import { ExternalLink } from "lucide-react";
import type { ConflictChoice, DryRunView, SourceRegistration, WriteBackView } from "../lib/api";
import { conflictActions, isVerifiedWriteSuccess } from "../lib/write-back-state";
import { DiffView } from "./diff-view";
import { DocumentIdentity, type DocumentIdentityData, shortId } from "./document-identity";
import { WorkflowProgress } from "./workflow-progress";
import { Button, InlineNotice, StateMark } from "./ui";

export function WriteBackResult({
  source,
  document,
  fileId,
  change,
  dryRun,
  result,
  deciding,
  onDecision,
  onStartAnother,
}: {
  source?: SourceRegistration;
  document?: DocumentIdentityData;
  fileId?: string | null;
  change?: { oldText: string | null; newText: string | null };
  dryRun?: DryRunView | null;
  result: WriteBackView;
  deciding: boolean;
  onDecision: (choice: ConflictChoice) => void;
  onStartAnother?: () => void;
}) {
  const identity = document ?? (source ? { name: source.source.name, revision: source.baseline.revision_id } : { name: "Google document", revision: result.baseline_revision_id });
  if (isVerifiedWriteSuccess(result.status, result.structurally_verified)) {
    return <VerifiedSuccess identity={identity} fileId={fileId ?? source?.source.provider_file_id ?? null} dryRun={dryRun} change={change} result={result} onStartAnother={onStartAnother} />;
  }
  if (result.status === "CONFLICT" && result.conflict) {
    return <ConflictState identity={identity} result={result} deciding={deciding} onDecision={onDecision} />;
  }
  return <AttentionState identity={identity} result={result} />;
}

function VerifiedSuccess({ identity, fileId, dryRun, change, result, onStartAnother }: { identity: DocumentIdentityData; fileId: string | null; dryRun?: DryRunView | null; change?: { oldText: string | null; newText: string | null }; result: WriteBackView; onStartAnother?: () => void }) {
  const verifiedDryRun = dryRun?.write_plan_id === result.write_plan_id && dryRun.write_plan_sha256 === result.write_plan_sha256
    ? dryRun
    : null;
  const preview = verifiedDryRun ?? result.preview;
  const items = verifiedChanges(preview, change);
  const multiple = items.length > 1;
  const checks = [
    result.backup_created ? "Versioned backup created" : null,
    result.backup_verified ? "Backup verified" : null,
    result.write_applied ? (multiple ? "Approved changes applied" : "Approved change applied") : null,
    result.resulting_revision_id ? "Google revision advanced" : null,
    result.structurally_verified ? "Resulting structure verified" : null,
  ].filter((item): item is string => item !== null);
  return (
    <div>
      <DocumentIdentity document={identity} />
      <WorkflowProgress current="Write-back" />
      <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.72fr)]">
        <section className="px-5 py-9 sm:px-8 lg:px-10 lg:py-10">
          <h2 className="type-page-title">{multiple ? "Changes written and verified" : "Change written and verified"}</h2>
          <p className="mt-2 text-[15px] text-muted">{multiple ? "The approved changes are now in Google Drive." : "The approved change is now in Google Drive."}</p>
          <p className="mt-5 text-[17px] font-semibold text-success">Write-back verified</p>

          {items.length ? (
            <div className="mt-9">
              <h3 className="text-[15.5px] font-semibold tracking-[-0.02em] text-ink">What changed</h3>
              <div className="mt-5 grid gap-8">
                {items.map((item, index) => (
                  <div key={item.proposal_id ?? String(index)}>
                    {multiple ? <p className="mb-3 text-[13px] font-semibold uppercase tracking-[0.04em] text-muted">Change {index + 1}</p> : null}
                    <DiffView oldText={item.old_text} newText={item.new_text} context={item.context} />
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <dl className="mt-7 surface-section divide-y divide-border-hair px-4 text-[14px]">
            <RevisionRow label="Previous revision" value={result.baseline_revision_id} />
            <RevisionRow label="Resulting revision" value={result.resulting_revision_id} />
          </dl>

          <div className="mt-6 grid gap-3">
            {fileId ? (
              <a href={`https://docs.google.com/document/d/${encodeURIComponent(fileId)}/edit`} target="_blank" rel="noreferrer" className="type-button inline-flex h-[34px] items-center justify-center gap-1.5 rounded-[9px] bg-primary px-3.5 text-primary-foreground shadow-[var(--shadow-subtle)] transition-colors duration-[var(--motion-duration)] hover:bg-primary-hover">
                Open in Google Drive <ExternalLink className="size-4" aria-hidden="true" />
              </a>
            ) : null}
            {onStartAnother ? <Button variant="secondary" onClick={onStartAnother}>Start another document</Button> : null}
          </div>
          <p className="mt-4 border-t border-border-hair pt-4 text-[12px] text-muted">Run complete</p>
        </section>

        <aside className="border-t border-border-light px-5 py-8 sm:px-8 lg:border-t-0 lg:border-l lg:px-8 lg:py-10">
          <h2 className="text-[15.5px] font-semibold tracking-[-0.02em] text-ink">Verification record</h2>
          <div className="mt-8">
            {checks.map((label, index) => (
              <div key={label} className="relative flex gap-3 pb-9 last:pb-0">
                {index < checks.length - 1 ? <span className="absolute top-[18px] bottom-0 left-[8.5px] w-px bg-primary-line" aria-hidden="true" /> : null}
                <StateMark state="complete" /><span className="text-[14px] text-ink">{label}</span>
              </div>
            ))}
          </div>
          {result.structurally_verified ? <p className="mt-7 border-t border-border-hair pt-6 text-[14px] leading-6 text-ink">Unrelated content remained unchanged.</p> : null}
        </aside>
      </div>
    </div>
  );
}

function ConflictState({ identity, result, deciding, onDecision }: { identity: DocumentIdentityData; result: WriteBackView; deciding: boolean; onDecision: (choice: ConflictChoice) => void }) {
  const conflict = result.conflict!;
  return (
    <div>
      <DocumentIdentity document={identity} />
      <WorkflowProgress current="Write-back" warning />
      <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.72fr)]">
        <section className="px-5 py-9 sm:px-8 lg:px-10 lg:py-10">
          <h2 className="type-page-title">Google Drive has a newer version</h2>
          <p className="mt-2 text-[15px] text-muted">DocRelay stopped before applying the approved change.</p>
          <div className="mt-5"><InlineNotice tone="warning"><strong>Nothing was silently overwritten.</strong></InlineNotice></div>

          <h3 className="mt-9 text-[15.5px] font-semibold tracking-[-0.02em] text-ink">What DocRelay found</h3>
          <dl className="mt-4 max-w-[560px] surface-section divide-y divide-border-hair px-4 text-[14px]">
            <RevisionRow label="Prepared from" value={conflict.baseline_revision_id} />
            <RevisionRow label="Latest in Drive" value={conflict.latest_revision_id} />
          </dl>
          <p className="mt-6 text-[14px] text-ink">The source changed after this write plan was prepared.</p>
          <p className="mt-2 text-[12px] text-muted">Detected {humanDetectionStage(conflict.detection_stage)}</p>

          <div className="mt-7 grid max-w-[650px] gap-3">
            {[...conflictActions].reverse().map((action) => (
              <Button key={action.choice} variant={action.choice === "REVIEW_LATEST" ? "primary" : "secondary"} busy={deciding} onClick={() => onDecision(action.choice)}>{action.label}</Button>
            ))}
          </div>
          <p className="mt-7 border-t border-border-hair pt-5 text-[13px] text-muted">The existing write plan remains stale and cannot be reused.</p>
        </section>

        <aside className="border-t border-border-light px-5 py-8 sm:px-8 lg:border-t-0 lg:border-l lg:px-8 lg:py-10">
          <h2 className="text-[15.5px] font-semibold tracking-[-0.02em] text-ink">Safe stop</h2>
          <div className="mt-8">
            {["Review preserved", "Revision mismatch detected", "Google write not applied"].map((label) => (
              <div key={label} className="relative flex gap-3 pb-10">
                <span className="absolute top-[18px] bottom-0 left-[8.5px] w-px bg-border-light" aria-hidden="true" />
                <StateMark state="complete" /><span className="text-[14px] text-ink">{label}</span>
              </div>
            ))}
            <div className="flex gap-3"><StateMark /><span className="text-[14px] text-ink">New review required</span></div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function AttentionState({ identity, result }: { identity: DocumentIdentityData; result: WriteBackView }) {
  const unknown = result.status === "ATTENTION";
  const inProgress = result.status === "IN_PROGRESS";
  const title = unknown ? "External effect needs verification" : inProgress ? "Write-back in progress" : "Safe write-back stopped";
  const message = unknown
    ? "DocRelay cannot prove the external outcome yet. It will not start another write automatically."
    : inProgress
      ? "The server has already claimed this workflow. No second write was started."
      : result.status === "CANCELLED"
        ? "Write-back was cancelled. No DocRelay change was applied."
        : result.status === "REVIEW_LATEST"
          ? "The previous plan is stale. Review the latest Google version before preparing another write."
          : "The safety pipeline stopped before a verified result was available.";
  return (
    <div>
      <DocumentIdentity document={identity} />
      <WorkflowProgress current="Write-back" warning />
      <section className="mx-auto max-w-[780px] px-5 py-14 sm:px-8 lg:py-20">
        <h2 className="type-page-title">{title}</h2>
        <div className="mt-6"><InlineNotice tone={unknown ? "info" : "warning"}>{message}</InlineNotice></div>
        {result.attention_code ? <p className="mt-5 font-mono text-[11px] text-muted">{result.attention_code}</p> : null}
      </section>
    </div>
  );
}

function RevisionRow({ label, value }: { label: string; value: string | null }) {
  return <div className="grid grid-cols-[160px_1fr] gap-4 py-3"><dt className="text-muted">{label}</dt><dd className="font-mono text-[12px] text-ink">{value ? shortId(value) : "—"}</dd></div>;
}

function humanDetectionStage(stage: string): string {
  return stage.replaceAll("_", " ").toLowerCase();
}

function verifiedChanges(
  preview: DryRunView | WriteBackView["preview"] | null | undefined,
  change?: { oldText: string | null; newText: string | null },
): Array<{ proposal_id?: string | null; old_text: string | null; new_text: string | null; context?: DryRunView["context"] }> {
  if (preview && "changes" in preview && preview.changes && preview.changes.length > 0) {
    return preview.changes;
  }
  const oldText = preview && "old_text" in preview ? preview.old_text : change?.oldText ?? null;
  const newText = preview && "new_text" in preview ? preview.new_text : change?.newText ?? null;
  if (!oldText && !newText) return [];
  return [{ old_text: oldText ?? null, new_text: newText ?? null, context: preview && "context" in preview ? preview.context : undefined }];
}
