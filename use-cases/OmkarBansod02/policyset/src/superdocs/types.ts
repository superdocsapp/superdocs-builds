export const SUPERDOCS_API_BASE = "https://api.superdocs.app/v1";

export const DOCX_MIME =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export const PDF_MIME = "application/pdf";

export const SUPERDOCS_OPEN_MODES = ["replace", "background"] as const;

export type SuperDocsOpenMode = (typeof SUPERDOCS_OPEN_MODES)[number];

export const SUPERDOCS_JOB_STATUSES = [
  "pending",
  "in_progress",
  "awaiting_approval",
  "completed",
  "failed",
  "cancelled",
] as const;

export type SuperDocsJobStatus = (typeof SUPERDOCS_JOB_STATUSES)[number];

export const PROPOSAL_OPERATIONS = ["edit", "create", "delete"] as const;

export type ProposalOperation = (typeof PROPOSAL_OPERATIONS)[number];

export type ExportFormat = "docx" | "pdf";

/**
 * SuperDocs `document_id` is session-local. Always store both identifiers
 * together; never treat a document_id as globally unique.
 */
export type SessionDocumentIdentity = {
  sessionId: string;
  documentId: string;
  durableDocumentId?: string;
};

export type IngestedDocument = {
  identity: SessionDocumentIdentity;
  versionId: string;
  filename: string | null;
  chunksCount: number | null;
};

export type SessionDocument = {
  identity: SessionDocumentIdentity;
  title: string | null;
  focused: boolean;
  versionId: string | null;
  chunksCount: number | null;
  html: string | null;
};

export type FocusedDocument = {
  identity: SessionDocumentIdentity;
  focused: boolean;
  versionId: string | null;
};

export type StartChatInput = {
  sessionId: string;
  message: string;
  /**
   * Optional. Omit for an unpinned multi-document request.
   * When provided it must be a non-empty session-local or durable id.
   */
  documentId?: string;
};

export type JobReference = {
  jobId: string;
  sessionId: string;
  status: SuperDocsJobStatus;
};

export type PendingChange = {
  changeId: string;
  operation: ProposalOperation;
  documentId: string;
  chunkId: string | null;
  oldHtml: string | null;
  newHtml: string | null;
  aiExplanation: string | null;
};

export type JobSnapshot = {
  reference: JobReference;
  progress: number | null;
  awaitingKind: string | null;
  /**
   * Normalized list. SuperDocs may send `pending_changes: null` while
   * `in_progress`; that is treated as no batch yet, not as an empty review.
   */
  pendingChanges: readonly PendingChange[];
  errorCode: string | null;
};

export type ReviewDecision = {
  changeId: string;
  approved: boolean;
  feedback?: string;
};

export type ReviewReceipt = {
  status: string;
  batchComplete: boolean;
};

export type ExportArtifact = {
  format: ExportFormat;
  bytes: Uint8Array;
  contentType: string;
  sha256: string;
  sizeBytes: number;
  contentDisposition: string | null;
  warnings: readonly Record<string, unknown>[];
};

export type SuperDocsClientOptions = {
  apiKey: string;
  apiBase?: string;
  fetch?: typeof fetch;
};
