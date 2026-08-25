/**
 * Types shared with the server API.
 *
 * There are no ServiceNow fixtures and no document generation in here: the
 * browser reads changes from `/api/changes` and every document operation is a
 * real SuperDocs call made server-side, where the API key stays.
 *
 * The server also decides what the reviewer should do next (`nextAction`). The
 * browser renders that decision rather than making its own, so the rail, the
 * highlighted button and the coaching copy can never disagree.
 */

export type WorkflowState =
  | "RECEIVED"
  | "UPLOADED"
  | "EDITING"
  | "REVIEW_REQUIRED"
  | "APPROVED"
  | "EXPORTED"
  | "INVALID_INPUT"
  | "FAILED";

export type Validation = {
  ok: boolean;
  missingFields: string[];
};

export type ChangeRequest = {
  id: string;
  number: string;
  short_description: string;
  configuration_item: string;
  work_notes: string;
  resolution_code: string;
  status: string;
  requester: string;
  assignment_group: string;
  risk: string;
  planned_start: string | null;
  planned_end: string | null;
};

export type ChangeListItem = ChangeRequest & { validation: Validation };

export type DocumentSection = {
  title: string;
  content: string;
  sourceField: keyof ChangeRequest;
};

export type VerificationFinding = {
  field: string;
  blocking: boolean;
  reason: string;
};

export type ChangeVerdict = "safe" | "advisory" | "blocked";

export type ChangeVerification = {
  verdict: ChangeVerdict;
  recommendation: "approve" | "reject";
  findings: VerificationFinding[];
};

export type ProposedChange = {
  changeId: string;
  chunkId: string | null;
  operation: string;
  explanation: string | null;
  before: string | null;
  after: string | null;
  decided: boolean;
  decision: boolean | null;
  verification: ChangeVerification;
};

export type PreservationCheck = {
  field: string;
  label: string;
  expected: string;
  found: boolean;
};

export type PreservationResult = {
  ok: boolean;
  checks: PreservationCheck[];
};

export type ActivityEvent = {
  sequence: number;
  type: string;
  content: string;
  at: string | null;
};

export type AuditEvent = {
  at: string;
  type: string;
  [key: string]: unknown;
};

export type WriteBackResult = {
  ok: boolean;
  at: string;
  detail?: string;
};

/** The single next thing the reviewer should do, decided server-side. */
export type NextAction = {
  id:
    | "restart"
    | "continue"
    | "reject-blocked"
    | "decide"
    | "wait"
    | "blocked-final"
    | "approve"
    | "export"
    | "done";
  label: string;
  detail: string | null;
  tone: "primary" | "danger" | "success" | "neutral";
  count?: number;
};

export type UploadResult = {
  sessionId: string;
  change: ChangeRequest;
  sections: DocumentSection[];
  filename: string;
  sourceHtml: string | null;
  versionId: string | null;
  chunksCount: number | null;
  quota: Quota | null;
};

export type JobState = {
  sessionId: string;
  status: string;
  progress: number | null;
  awaitingKind: "change_batch" | "continue_prompt" | null;
  awaitingApproval: boolean;
  awaitingContinue: boolean;
  finished: boolean;
  failed: boolean;
  summary: string | null;
  proposedChanges: ProposedChange[];
  activity: ActivityEvent[];
  documentHtml: string | null;
  versionId: string | null;
  verification: PreservationResult | null;
  approved: boolean;
  approvedAt: string | null;
  reviewer: string | null;
  checksum: string | null;
  readyToApprove: boolean;
  exportReady: boolean;
  exported: boolean;
  writeBack: WriteBackResult | null;
  audit: AuditEvent[];
  nextAction: NextAction;
  error: unknown;
};

export type Quota = {
  tier: string | null;
  used: number | null;
  remaining: number | null;
  limit: number | null;
  resetsAt: string | null;
};

/**
 * Connection status for the two systems this app sits between.
 *
 * Deliberately narrow: whether each is answering, not how either is reached.
 * Deployment topology is an operational concern and does not belong in a
 * payload every browser tab fetches.
 */
export type ServiceHealth = {
  ok: boolean;
  serviceNow: {
    connected: boolean;
    writeBack: boolean;
  };
  superDocs: {
    connected: boolean;
    /** A replayed run is always labelled as one. */
    replaying: boolean;
    quota: Quota | null;
  };
  runs: number;
};

export const stepIndexByState: Record<WorkflowState, number> = {
  RECEIVED: 0,
  UPLOADED: 1,
  EDITING: 2,
  REVIEW_REQUIRED: 3,
  APPROVED: 4,
  EXPORTED: 5,
  INVALID_INPUT: 0,
  FAILED: 2
};

/** Chunk HTML is rendered as text in the diff view; it is never re-injected as markup. */
export function htmlToPlainText(html: string | null | undefined): string {
  if (!html) return "";
  return html
    .replace(/<(script|style)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|h[1-6]|li|tr|td|th)>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function formatDate(value?: string | null) {
  if (!value) return "Not scheduled";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function formatTime(value?: string | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}

export function describeVerdict(verdict: ChangeVerdict) {
  switch (verdict) {
    case "blocked":
      return "Alters a ServiceNow value";
    case "advisory":
      return "Review before approving";
    default:
      return "Safe to approve";
  }
}

/**
 * Why a verdict was reached, in the reviewer's terms. The findings say what
 * diverged; this says what the rule is, so the gate reads as a policy rather
 * than an opinion.
 */
export function explainVerdict(verdict: ChangeVerdict) {
  switch (verdict) {
    case "blocked":
      return "ServiceNow owns this value and the document must carry it character for character. The server refuses to approve this change even if the browser asks.";
    case "advisory":
      return "This touches a ServiceNow-owned field that is not export-blocking. It is your call.";
    default:
      return "Every ServiceNow-owned value in this chunk survived unchanged.";
  }
}

const ACTIVITY_LABELS: Record<string, string> = {
  document_sync: "Document synced",
  user_facing: "SuperDocs",
  intermediate: "Working",
  proposed_change_batch: "Proposed a batch of changes",
  continue_prompt: "Paused for a decision"
};

export function describeActivity(event: ActivityEvent) {
  return ACTIVITY_LABELS[event.type] ?? event.type.replace(/_/g, " ");
}

const AUDIT_LABELS: Record<string, string> = {
  uploaded: "Uploaded to SuperDocs",
  edit_started: "Edit requested",
  change_approved: "Change approved",
  change_rejected: "Change rejected",
  batch_decided: "Batch decided",
  chunk_reedited: "Section re-edited",
  continue_resumed: "Continued the edit",
  continue_stopped: "Stopped the edit",
  document_approved: "Document approved",
  approval_refused: "Approval refused",
  exported: "Exported",
  export_refused: "Export refused",
  servicenow_updated: "ServiceNow updated",
  servicenow_update_failed: "ServiceNow update failed"
};

export function describeAudit(event: AuditEvent) {
  return AUDIT_LABELS[event.type] ?? event.type.replace(/_/g, " ");
}

/**
 * The audit event's payload, minus the two fields already shown as the row.
 * Empty values are dropped rather than rendered as "reviewer: null" — an
 * absent detail is not a detail.
 */
export function auditDetail(event: AuditEvent) {
  return Object.entries(event)
    .filter(([key]) => key !== "at" && key !== "type")
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${String(value)}`)
    .join(" · ");
}
