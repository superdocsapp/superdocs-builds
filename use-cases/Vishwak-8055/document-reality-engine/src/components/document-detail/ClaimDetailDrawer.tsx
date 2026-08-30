import { useState } from "react";
import type { Claim, SDDocument } from "../../types/domain";
import { traceClaim } from "../../domain/provenance";
import { formatDateTime } from "../../domain/utils";
import { useAppStore } from "../../store/appStore";
import { Drawer } from "../ui/Drawer";
import { VerificationBadge } from "../ui/Badge";
import { ProvenanceThread } from "./ProvenanceThread";

export function ClaimDetailDrawer({ document, claim, onClose }: { document: SDDocument; claim: Claim | null; onClose: () => void }) {
  const verifyClaim = useAppStore((s) => s.verifyClaim);
  const addComment = useAppStore((s) => s.addComment);
  const [commentText, setCommentText] = useState("");

  const trace = claim ? traceClaim(document, claim.id) : null;
  const comments = claim ? document.comments.filter((c) => c.targetType === "Claim" && c.targetId === claim.id) : [];

  return (
    <Drawer open={Boolean(claim)} onClose={onClose} title="Claim detail" subtitle={claim ? document.title : undefined}>
      {claim && trace && (
        <div className="space-y-6 p-5">
          <div>
            <VerificationBadge status={claim.verificationStatus} />
            <p className="mt-2 text-base leading-snug text-text-primary">{claim.text}</p>
            <p className="mt-1 text-xs text-text-tertiary">Claimed by {claim.claimant}</p>
            {claim.contradictionNote && (
              <p className="mt-3 rounded-md border border-critical/20 bg-critical-soft px-3 py-2 text-xs leading-relaxed text-critical">
                {claim.contradictionNote}
              </p>
            )}
          </div>

          <div>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-tertiary">Provenance</h3>
            <ProvenanceThread nodes={trace.nodes} />
          </div>

          {claim.verificationStatus !== "Verified" && (
            <button
              onClick={() => verifyClaim(document.id, claim.id)}
              className="w-full rounded-md bg-trust px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-trust-strong"
            >
              Mark as verified
            </button>
          )}

          <div>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-tertiary">Comments</h3>
            {comments.length === 0 ? (
              <p className="text-sm text-text-tertiary">No comments yet.</p>
            ) : (
              <ul className="space-y-3">
                {comments.map((comment) => (
                  <li key={comment.id} className="text-sm">
                    <p className="text-text-primary">{comment.text}</p>
                    <p className="mt-0.5 text-xs text-text-tertiary">
                      {comment.author} · {formatDateTime(comment.createdAt)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!commentText.trim()) return;
                addComment(document.id, "Claim", claim.id, commentText);
                setCommentText("");
              }}
              className="mt-3 flex gap-2"
            >
              <input
                value={commentText}
                onChange={(event) => setCommentText(event.target.value)}
                placeholder="Add a comment…"
                aria-label="Add a comment"
                className="flex-1 rounded-md border border-line px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:border-trust focus:outline-none"
              />
              <button
                type="submit"
                disabled={!commentText.trim()}
                className="rounded-md bg-paper-100 px-3 py-1.5 text-sm font-medium text-text-primary transition-colors hover:bg-paper-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Post
              </button>
            </form>
          </div>
        </div>
      )}
    </Drawer>
  );
}
