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

export interface WriterPort {
  initialize(): Promise<void>;
  getSelectedHtml(): Promise<string>;
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
  exportDocument(sessionId: string): Promise<Blob>;
}
