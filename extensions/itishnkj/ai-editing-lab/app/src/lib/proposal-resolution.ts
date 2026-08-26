import type { EditResult } from '@workspace/api-client-react';

/** Minimal shape the resolution sequence needs from a pending proposal. */
export type SiblingProposal = Pick<
  EditResult,
  'engine' | 'engineLabel' | 'requestId' | 'review'
>;

export type SiblingResolutionOutcome<T extends SiblingProposal> =
  | { ok: true }
  | { ok: false; failed: T };

/**
 * Resolve every OTHER pending proposal before one is accepted.
 *
 * Order matters and is part of the contract:
 * 1. Every sibling with an open hosted review is cancelled server-side, one
 *    at a time, and its terminal `cancelled` state is recorded ONLY after the
 *    server confirms the cancellation.
 * 2. If any cancellation fails, resolution stops immediately and reports the
 *    failing sibling. The caller must abort the acceptance so the sibling
 *    keeps its pending review in the UI — accepting again retries the
 *    cancellation, and the review card's own controls remain available.
 *    Nothing is recorded for the failed sibling, and completed siblings are
 *    left pending (they are recorded on the retry).
 * 3. Only after every hosted sibling is confirmed cancelled are the
 *    completed (non-review) siblings recorded as rejected.
 */
export async function resolveSiblingProposals<T extends SiblingProposal>(options: {
  siblings: T[];
  cancelHostedReview: (reviewId: string) => Promise<void>;
  onCancelled: (sibling: T) => void;
  onRejected: (sibling: T) => void;
}): Promise<SiblingResolutionOutcome<T>> {
  const { siblings, cancelHostedReview, onCancelled, onRejected } = options;

  for (const sibling of siblings) {
    if (!sibling.review) continue;
    try {
      await cancelHostedReview(sibling.review.reviewId);
    } catch {
      return { ok: false, failed: sibling };
    }
    onCancelled(sibling);
  }

  for (const sibling of siblings) {
    if (!sibling.review) onRejected(sibling);
  }

  return { ok: true };
}

export type HostedAcceptFlowResult<R> =
  | { status: 'aborted-sibling-resolution' }
  | { status: 'completed'; resolved: R };

/**
 * Ordering contract for accepting a HOSTED proposal while other proposals
 * are pending: every sibling is fully resolved FIRST (hosted cancellations
 * server-confirmed via `resolveSiblingProposals`), and only then is the
 * selected hosted review accepted server-side. If sibling resolution fails,
 * the flow aborts BEFORE the hosted accept request is ever sent, so the
 * selected proposal remains pending and retryable and no server-side state
 * has changed for it. This applies to the FIRST batch of a multi-batch
 * review — later batches have no remaining siblings.
 */
export async function runHostedAcceptFlow<R>(options: {
  resolveSiblings: () => Promise<boolean>;
  decideReview: () => Promise<R>;
}): Promise<HostedAcceptFlowResult<R>> {
  if (!(await options.resolveSiblings())) {
    return { status: 'aborted-sibling-resolution' };
  }
  return { status: 'completed', resolved: await options.decideReview() };
}
