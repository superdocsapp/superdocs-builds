export type EngineId = "diy" | "superdocs";

export interface EngineEditRequest {
  documentHtml: string;
  selectionHtml?: string | null;
  selectionText?: string | null;
  selectionFrom?: number | null;
  selectionTo?: number | null;
  scope: "selection" | "document";
  instruction: string;
  preset?: string | null;
  requestId: string;
  currentVersionId: string;
}

export interface EngineUsage {
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
  hostedUsage: string | null;
}

export interface RequestMetrics {
  promptChars: number | null;
  contextChars: number;
}

export interface HostedReview {
  reviewId: string;
  state: "awaiting_approval";
  batchNumber: number;
}
export interface EngineEditResult {
  engine: EngineId;
  engineLabel: string;
  promptVersion: string;
  requestId: string;
  success: boolean;
  proposedChanges: Array<{
    id: string;
    operation: "edit" | "create" | "delete";
    oldHtml: string | null;
    newHtml: string | null;
    explanation: string | null;
    target: string | null;
    chunkId: string | null;
    status: "pending" | "accepted" | "rejected";
  }>;
  candidateDocumentHtml: string | null;
  assistantMessage: string | null;
  latencyMs: number;
  reviewWaitMs: number | null;
  usage: EngineUsage | null;
  requestMetrics: RequestMetrics;
  retryCount: number;
  error: string | null;
  review: HostedReview | null;
  startedAt: string;
  completedAt: string;
}

export interface EngineReviewDecision {
  changeId: string;
  approved: boolean;
  feedback?: string | null;
}

export interface EditingEngine {
  readonly id: EngineId;
  readonly label: string;
  edit(request: EngineEditRequest): Promise<EngineEditResult>;
}

export interface ReviewDecisionRequest {
  reviewId: string;
  decision: "accept" | "reject";
  changeIds: string[];
}
export class EngineUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EngineUnavailableError";
  }
}

export interface HostedReviewEngine extends EditingEngine {
  decideReview(request: ReviewDecisionRequest): Promise<EngineEditResult>;
  cancelReview(reviewId: string): Promise<EngineEditResult>;
}
