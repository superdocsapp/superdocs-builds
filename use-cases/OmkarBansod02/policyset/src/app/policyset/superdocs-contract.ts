import type { PolicyDocumentType } from "@/domain";

export type PolicyDocumentExportFormat = "docx" | "pdf";

export type SuperDocsWorkspaceSession = {
  sessionId: string;
  documentIds: Record<PolicyDocumentType, string>;
};

export type SuperDocsProposal = {
  changeId: string;
  operation: "edit" | "create" | "delete";
  documentId: string;
  chunkId: string | null;
  beforeHtml: string | null;
  afterHtml: string | null;
  explanation: string | null;
};

export type SuperDocsJobView = {
  jobId: string;
  sessionId: string;
  status:
    | "pending"
    | "in_progress"
    | "awaiting_approval"
    | "completed"
    | "failed"
    | "cancelled";
  progress: number | null;
  proposals: readonly SuperDocsProposal[];
  errorCode: string | null;
};

export type SuperDocsSessionDocumentView = {
  documentId: string;
  title: string | null;
  html: string | null;
  normalizedContent: string | null;
  sha256: string | null;
};

export type PolicyDocumentContentState = {
  documentId: string;
  normalizedContent: string;
  sha256: string;
};

export type PolicyDocumentContentStateMap = Record<
  PolicyDocumentType,
  PolicyDocumentContentState
>;

export type SuperDocsTargetedJob = {
  documentType: PolicyDocumentType;
  job: SuperDocsJobView;
};

export type SuperDocsSynchronizedStartView = {
  jobs: readonly SuperDocsTargetedJob[];
  preEditState: PolicyDocumentContentStateMap;
};

export type SuperDocsReviewView = {
  status: string;
  batchComplete: boolean;
  decisionCount: number;
};
