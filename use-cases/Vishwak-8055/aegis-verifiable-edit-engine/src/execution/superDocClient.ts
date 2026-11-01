/**
 * This interface is deliberately NOT a 1:1 wrapper of the real `superdoc`
 * npm package — see docs/ARCHITECTURE.md "SuperDoc integration" for why.
 * SuperDoc (https://docs.superdoc.dev) is a real, open-source, self-hosted
 * DOCX engine (not a hosted SaaS API), with a documented Query → Target →
 * Mutate → Receipt operation contract and a tracked-changes review flow
 * (`doc.trackChanges.list/get/decide`) built specifically for "let an agent
 * propose an edit, let a reviewer accept or reject it". That review flow is
 * the natural integration point for a verification layer, so this interface
 * mirrors its shape (propose a tracked change → inspect → decide) rather
 * than inventing an unrelated one.
 *
 * What real SuperDoc does NOT give Aegis for free is an agent that decides
 * *which* `doc.replace` / `doc.query.match` calls to make from a natural-
 * language instruction — that is a separate, substantial piece of engineering
 * (an editing agent) that sits on the other side of this interface. Aegis
 * consumes whatever that agent (or a human, or SuperDoc's own AI features)
 * proposed; it does not drive the low-level document mutation itself.
 */

export interface SuperDocReceipt {
  status: 'applied' | 'rejected' | 'error';
  operation: string;
  detail: string;
}

export interface ProposedEdit {
  operationId: string;
  changeMode: 'tracked';
  receipt: SuperDocReceipt;
  /** Aegis-canonical pseudo-markdown source (see src/verification/normalize.ts) representing the proposed "after" state. */
  resultDocument: string;
}

export interface SuperDocSession {
  readonly sessionId: string;
  proposeEdit(instructionText: string): Promise<ProposedEdit>;
  decideTrackedChanges(decision: 'accept' | 'reject'): Promise<SuperDocReceipt>;
  close(): Promise<void>;
}

export interface OpenDocumentInput {
  documentId: string;
  content: string;
}

export interface SuperDocClient {
  readonly mode: 'mock' | 'live';
  open(input: OpenDocumentInput): Promise<SuperDocSession>;
}
