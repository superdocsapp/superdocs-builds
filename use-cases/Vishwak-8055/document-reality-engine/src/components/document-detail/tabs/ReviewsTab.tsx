import { useState } from "react";
import clsx from "clsx";
import { MessageSquare } from "lucide-react";
import type { SDDocument } from "../../../types/domain";
import { useAppStore } from "../../../store/appStore";
import { computeRisk } from "../../../domain/risk";
import { unresolvedRequirements } from "../../../domain/compliance";
import { formatDate, formatDateTime } from "../../../domain/utils";
import { ActionStatusBadge, DocumentStatusBadge } from "../../ui/Badge";
import { ConfirmDialog, Modal } from "../../ui/Modal";

export function ReviewsTab({ document }: { document: SDDocument }) {
  const approveDocument = useAppStore((s) => s.approveDocument);
  const requestChanges = useAppStore((s) => s.requestChanges);
  const completeAction = useAppStore((s) => s.completeAction);
  const assignAction = useAppStore((s) => s.assignAction);

  const [approveOpen, setApproveOpen] = useState(false);
  const [changesOpen, setChangesOpen] = useState(false);
  const [changesNote, setChangesNote] = useState("");
  const [reassigningId, setReassigningId] = useState<string | null>(null);
  const [assigneeDraft, setAssigneeDraft] = useState("");

  const risk = computeRisk(document);
  const unresolvedReqs = unresolvedRequirements(document.requirements);
  const canApproveCleanly = risk.openCount === 0 && unresolvedReqs.length === 0;
  const isFinal = document.status === "Approved" || document.status === "Published" || document.status === "Deprecated";

  return (
    <div className="space-y-8">
      <section className="flex flex-col gap-4 rounded-md border border-line bg-paper-0 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <DocumentStatusBadge status={document.status} />
          <p className="mt-2 text-xs text-text-tertiary">
            Owned by {document.owner.name} ({document.owner.role})
          </p>
        </div>
        {!isFinal && (
          <div className="flex gap-2">
            <button
              onClick={() => setChangesOpen(true)}
              className="rounded-md border border-line px-3.5 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-paper-100"
            >
              Request changes
            </button>
            <button
              onClick={() => setApproveOpen(true)}
              className="rounded-md bg-trust px-3.5 py-2 text-sm font-medium text-white transition-colors hover:bg-trust-strong"
            >
              Approve
            </button>
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-text-primary">Decisions</h2>
        {document.decisions.length === 0 ? (
          <p className="text-sm text-text-tertiary">No decisions recorded yet.</p>
        ) : (
          <ul className="space-y-2">
            {[...document.decisions].reverse().map((decision) => (
              <li key={decision.id} className="rounded-md border border-line bg-paper-0 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium text-text-primary">{decision.description}</p>
                  <span className="font-numeric text-xs text-text-tertiary">{formatDate(decision.decidedAt)}</span>
                </div>
                <p className="mt-1 text-xs text-text-tertiary">
                  {decision.outcome} by {decision.decidedBy}
                </p>
                {decision.notes && <p className="mt-1.5 text-sm text-text-secondary">{decision.notes}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-text-primary">Actions</h2>
        {document.actions.length === 0 ? (
          <p className="text-sm text-text-tertiary">No actions have been assigned for this document.</p>
        ) : (
          <ul className="divide-y divide-line rounded-md border border-line bg-paper-0">
            {document.actions.map((action) => (
              <li key={action.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className={clsx("text-sm font-medium", action.status === "Done" ? "text-text-tertiary line-through" : "text-text-primary")}>
                    {action.title}
                  </p>
                  <p className="mt-0.5 text-xs text-text-tertiary">{action.description}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-tertiary">
                    {reassigningId === action.id ? (
                      <form
                        onSubmit={(event) => {
                          event.preventDefault();
                          if (assigneeDraft.trim()) assignAction(document.id, action.id, assigneeDraft);
                          setReassigningId(null);
                        }}
                        className="flex items-center gap-1.5"
                      >
                        <input
                          autoFocus
                          value={assigneeDraft}
                          onChange={(event) => setAssigneeDraft(event.target.value)}
                          aria-label="Reassign to"
                          className="rounded border border-line-strong px-1.5 py-0.5 text-xs text-text-primary focus:border-trust focus:outline-none"
                        />
                        <button type="submit" className="font-medium text-trust">
                          Save
                        </button>
                        <button type="button" onClick={() => setReassigningId(null)} className="text-text-tertiary">
                          Cancel
                        </button>
                      </form>
                    ) : (
                      <button
                        onClick={() => {
                          setReassigningId(action.id);
                          setAssigneeDraft(action.assignee);
                        }}
                        className="underline decoration-dotted underline-offset-2 hover:text-text-primary"
                      >
                        {action.assignee}
                      </button>
                    )}
                    <span>· due {formatDate(action.dueDate)}</span>
                    <span>· {action.priority} priority</span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <ActionStatusBadge status={action.status} />
                  {action.status !== "Done" && (
                    <button
                      onClick={() => completeAction(document.id, action.id)}
                      className="rounded-md border border-line px-2.5 py-1 text-xs font-medium text-text-secondary transition-colors hover:bg-paper-100"
                    >
                      Complete
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-text-primary">
          <MessageSquare className="h-4 w-4" aria-hidden="true" />
          Comments
        </h2>
        {document.comments.length === 0 ? (
          <p className="text-sm text-text-tertiary">No comments yet.</p>
        ) : (
          <ul className="space-y-3">
            {[...document.comments].reverse().map((comment) => (
              <li key={comment.id} className="rounded-md border border-line bg-paper-0 p-3 text-sm">
                <p className="text-text-primary">{comment.text}</p>
                <p className="mt-1 text-xs text-text-tertiary">
                  {comment.author} on {comment.targetType} · {formatDateTime(comment.createdAt)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={approveOpen}
        onClose={() => setApproveOpen(false)}
        onConfirm={() => {
          approveDocument(document.id);
          setApproveOpen(false);
        }}
        title="Approve this document?"
        confirmLabel="Approve"
        tone={canApproveCleanly ? "default" : "critical"}
        description={
          canApproveCleanly ? (
            "All requirements are satisfied and there are no open risk findings."
          ) : (
            <span>
              This document still has <strong>{risk.openCount} open risk finding{risk.openCount === 1 ? "" : "s"}</strong> and{" "}
              <strong>
                {unresolvedReqs.length} unresolved requirement{unresolvedReqs.length === 1 ? "" : "s"}
              </strong>
              . Approving now will record your decision alongside these open items.
            </span>
          )
        }
      />

      <Modal open={changesOpen} onClose={() => setChangesOpen(false)} title="Request changes">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!changesNote.trim()) return;
            requestChanges(document.id, changesNote);
            setChangesNote("");
            setChangesOpen(false);
          }}
        >
          <div className="px-5 py-4">
            <h2 className="text-sm font-semibold text-text-primary">Request changes</h2>
            <label htmlFor="changes-note" className="mt-3 block text-xs font-medium text-text-tertiary">
              What needs to change?
            </label>
            <textarea
              id="changes-note"
              value={changesNote}
              onChange={(event) => setChangesNote(event.target.value)}
              rows={4}
              autoFocus
              placeholder="e.g. Need an updated SOC 2 report before this can move forward."
              className="mt-1.5 w-full rounded-md border border-line px-3 py-2 text-sm text-text-primary placeholder:text-text-tertiary focus:border-trust focus:outline-none"
            />
          </div>
          <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
            <button
              type="button"
              onClick={() => setChangesOpen(false)}
              className="rounded-md px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:bg-paper-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!changesNote.trim()}
              className="rounded-md bg-trust px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-trust-strong disabled:cursor-not-allowed disabled:opacity-50"
            >
              Submit
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
