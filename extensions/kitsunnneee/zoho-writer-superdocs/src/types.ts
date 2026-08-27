export type JobStatus =
  | "pending"
  | "in_progress"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled"
  | "unknown";

export type ChangeOperation = "edit" | "create" | "delete" | "unknown";

export interface PendingChange {
  id: string;
  operation: ChangeOperation;
  chunkId?: string;
  insertAfterChunkId?: string;
  oldHtml: string;
  newHtml: string;
  explanation: string;
}

export interface Usage {
  monthlyUsed?: number;
  monthlyLimit?: number;
  monthlyRemaining?: number;
  operationsCharged?: number;
  wasBillable?: boolean;
}

export interface NormalizedJob {
  jobId?: string;
  sessionId?: string;
  status: JobStatus;
  progress?: number;
  changes: PendingChange[];
  awaitingKind?: string;
  usage?: Usage;
  updatedHtml?: string;
  error?: string;
  raw: unknown;
}

export interface ApprovalDecision {
  changeId: string;
  approved: boolean;
  feedback?: string;
}

export interface ApprovalPayload {
  job_id: string;
  approved: boolean;
  changes: Array<{
    change_id: string;
    approved: boolean;
    feedback?: string;
  }>;
}

// Which format actually crossed the host relay intact, so the UI can name the
// file honestly instead of always claiming a .docx.
export interface ExportResult {
  blob: Blob;
  filename: string;
  format: "docx" | "html";
  note?: string;
}

// "applied" means the document was observed to change. "unverified" means the
// host accepted the call and cleared the selection, leaving nothing to compare —
// it must not be reported as success. A host that changes nothing throws instead.
export type HostWriteOutcome = "applied" | "unverified";

export interface HostWriteResult {
  event: string;
  outcome: HostWriteOutcome;
}

export interface WriterPort {
  initialize(): Promise<void>;
  getSelectedHtml(): Promise<string>;
  replaceSelection(html: string, expectedHtml: string): Promise<HostWriteResult>;
}

export interface SuperDocsPort {
  upload(html: string, sessionId: string): Promise<unknown>;
  startChat(sessionId: string, instruction: string): Promise<unknown>;
  getJob(jobId: string): Promise<unknown>;
  approve(sessionId: string, payload: ApprovalPayload): Promise<unknown>;
  continueChat(
    sessionId: string,
    jobId: string,
    shouldContinue: boolean,
  ): Promise<unknown>;
  exportDocument(sessionId: string): Promise<ExportResult>;
}
