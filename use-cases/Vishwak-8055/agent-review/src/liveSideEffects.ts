import { canSafelyRoundTrip, parseChunks, serializeChunks } from "./chunkDiff";
import { WriteBackRefusedError, type SuperDocsSideEffects } from "./reviewStore";
import { applyRevertPatch, type RevertPatch } from "./revertEngine";
import type { SuperDocsClient } from "./superdocsClient";

/**
 * Thrown instead of writing a reconstructed document back to SuperDocs when
 * `canSafelyRoundTrip` fails — i.e., when this extension's chunk model has
 * been empirically shown, against the actual live content, not to fully
 * capture this document's structure. Extends `WriteBackRefusedError` so
 * `ReviewStore` recognizes it as "refused, report a conflict" rather than a
 * transient failure to retry.
 */
export class UnsafeDocumentStructureError extends WriteBackRefusedError {
  constructor(sessionId: string) {
    super(
      `Refusing to write back to session ${sessionId}: this document's structure isn't fully captured by the local chunk model (round-trip check failed), so an automatic patch could silently drop or corrupt content. Safe automatic revert is unavailable for this document — resolve manually in SuperDocs.`
    );
    this.name = "UnsafeDocumentStructureError";
  }
}

/**
 * KNOWN LIMITATION (see docs/IMPLEMENTATION_PLAN.md §15 and README):
 *
 * SuperDocs's documented API has no plain "overwrite this document's HTML
 * verbatim, no AI involved" endpoint that this implementation could find or
 * verify. `POST /v1/chat` accepts an optional `document_html` input, but
 * it's still an AI-mediated edit call, not a guaranteed-deterministic
 * direct write — this sandbox's network egress doesn't reach
 * api.superdocs.app, so this path could not be smoke-tested against a real
 * account.
 *
 * Given that constraint, this is the strongest truthful implementation
 * available: compute the exact target document HTML client-side (using the
 * already-tested chunkDiff/revertEngine functions — no AI involved in
 * deciding *what* the content should become), then ask SuperDocs to accept
 * that content verbatim via a minimal, unambiguous instruction with
 * `approval_mode: "approve_all"`. If a live account shows this doesn't
 * apply deterministically in practice, this is the one method that needs
 * to change — everything upstream of it (the patch itself, the safety
 * check that produced it) is unaffected and already real/tested.
 */
export class LiveSuperDocsSideEffects implements SuperDocsSideEffects {
  constructor(private readonly client: SuperDocsClient) {}

  async decideHitlChange(args: {
    sessionId: string;
    jobId: string;
    changeId: string;
    approved: boolean;
    feedback?: string;
  }): Promise<void> {
    await this.client.approveChange(args.sessionId, args.jobId, {
      changeId: args.changeId,
      approved: args.approved,
      ...(args.feedback === undefined ? {} : { feedback: args.feedback }),
    });
  }

  async applyPatch(args: { sessionId: string; documentId: string; patch: RevertPatch }): Promise<void> {
    const history = await this.client.getSessionHistory(args.sessionId);
    const currentHtml = history.document_state?.html;
    if (currentHtml === undefined) {
      throw new Error(
        `Cannot apply patch: session ${args.sessionId} has no current document state to patch against.`
      );
    }

    // Do not attempt a write-back unless our chunk model has just been
    // empirically proven, against this exact live content, to fully
    // capture the document's structure. See canSafelyRoundTrip's docstring
    // and docs/SECURITY.md — this is the P0 document-integrity gate.
    if (!canSafelyRoundTrip(currentHtml)) {
      throw new UnsafeDocumentStructureError(args.sessionId);
    }

    const currentChunks = parseChunks(currentHtml);
    const patchedChunks = applyRevertPatch(currentChunks, args.patch);
    const targetHtml = serializeChunks(patchedChunks);

    await this.client.editDocument(
      args.sessionId,
      "Apply this exact document content with no further changes or improvements.",
      targetHtml
    );
  }
}
