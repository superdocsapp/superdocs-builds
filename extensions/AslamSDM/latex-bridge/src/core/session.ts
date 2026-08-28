import { SuperDocsClient } from "./client";
import {
  IngestWarning,
  PageSetup,
  ProposedChange,
  JobStatus,
} from "./types";

export interface SessionEvent {
  type:
    | "uploaded"
    | "chat_started"
    | "waiting"
    | "awaiting_approval"
    | "approved"
    | "denied"
    | "completed"
    | "failed"
    | "warnings";
  message?: string;
  jobId?: string;
  changes?: ProposedChange[];
  warnings?: IngestWarning[];
  stage?: string;
  approvedIds?: string[];
}

export interface SessionOptions {
  opBudget: number;
  pollIntervalMs: number;
  maxPollSeconds?: number;
  modelTier?: "core" | "turbo" | "pro" | "max";
}

export interface ApproveDecision {
  changeId: string;
  approved: boolean;
  feedback?: string;
}

/**
 * Orchestrates one SuperDocs editing session for a LaTeX project:
 * upload -> chat -> fast HITL approval -> (export/write-back handled by caller).
 */
export class BridgeSession {
  private opsUsed = 0;
  private appliedChanges: ProposedChange[] = [];
  private pendingApproval:
    | { jobId: string; changes: ProposedChange[]; resolve: (d: ApproveDecision[]) => void }
    | undefined;

  constructor(
    private client: SuperDocsClient,
    private sessionId: string,
    private options: SessionOptions,
    private emit: (e: SessionEvent) => void
  ) {}

  get opsCount(): number {
    return this.opsUsed;
  }

  get remainingBudget(): number {
    return this.options.opBudget - this.opsUsed;
  }

  /** Approved changes from the last edit round (for write-back). */
  get approvedChanges(): ProposedChange[] {
    return this.appliedChanges;
  }

  async uploadProject(
    zipBytes: Uint8Array,
    filename: string,
    contentType: string
  ): Promise<{
    sessionId: string;
    chunksCount?: number | null;
    versionId?: string | null;
    warnings: IngestWarning[];
    pageSetup?: PageSetup | null;
  }> {
    this.emit({ type: "uploaded", stage: "upload", message: "Requesting upload URL" });
    const up = await this.client.requestUploadUrl({
      filename,
      content_type: contentType,
      size_bytes: zipBytes.byteLength,
      purpose: "document",
    });
    this.emit({ type: "uploaded", stage: "upload", message: "Uploading project archive" });
    await this.client.putBytes(up.upload_url, zipBytes, contentType);
    this.emit({ type: "uploaded", stage: "parse", message: "Parsing LaTeX project" });
    const parsed = await this.client.processUpload(up.upload_id, {
      session_id: this.sessionId,
      filename,
      parse_mode: "document",
      return_html: false,
    });
    if (parsed.warnings && parsed.warnings.length > 0) {
      this.emit({ type: "warnings", warnings: parsed.warnings });
    }
    this.emit({
      type: "uploaded",
      stage: "parsed",
      message: `Parsed into ${parsed.chunks_count ?? "?"} editable sections`,
    });
    return {
      sessionId: parsed.session_id,
      chunksCount: parsed.chunks_count,
      versionId: parsed.version_id,
      warnings: parsed.warnings ?? [],
      pageSetup: parsed.page_setup,
    };
  }

  /** Ask the AI to edit. Every call consumes one op (budget guard enforced). */
  async requestEdit(message: string): Promise<JobStatus> {
    if (this.remainingBudget <= 0) {
      throw new Error(
        `Op budget exhausted (${this.options.opBudget} max per session). Export the current state or raise latexBridge.opBudgetPerSession.`
      );
    }
    const { job_id } = await this.client.chatAsync({
      message,
      session_id: this.sessionId,
      approval_mode: "ask_every_time",
      model_tier: this.options.modelTier,
    });
    this.opsUsed += 1;
    this.emit({ type: "chat_started", jobId: job_id, message });
    return this.pollForApprovals(job_id);
  }

  /**
   * Poll, and on each awaiting_approval pause, wait for the UI's decisions
   * (via submitDecisions). Approvals must land quickly — the AI auto-denies
   * stale proposals and self-iterates.
   */
  async pollForApprovals(jobId: string): Promise<JobStatus> {
    this.emit({ type: "waiting", jobId });
    return this.client.poll(jobId, {
      onAwaitingApproval: async (job, changes) => {
        if (this.pendingApproval) {
          throw new Error("approval already pending — submit decisions before approving again");
        }
        this.emit({ type: "awaiting_approval", jobId, changes });
        const decisions = await new Promise<ApproveDecision[]>((resolve) => {
          this.pendingApproval = { jobId, changes, resolve };
        });
        this.pendingApproval = undefined;
        if (decisions.length === 0) return;
        const batch = await this.client.approve(this.sessionId, {
          job_id: jobId,
          approved: true,
          changes: decisions.map((d) => ({ change_id: d.changeId, approved: d.approved, feedback: d.feedback })),
        });
        this.appliedChanges = changes.filter(
          (c) => decisions.find((d) => d.changeId === c.change_id)?.approved
        );
        const allApproved = decisions.every((d) => d.approved);
        this.emit({
          type: allApproved ? "approved" : "denied",
          jobId,
          changes,
          approvedIds: this.appliedChanges.map((c) => c.change_id),
          message: batch.message ?? "Approval processed",
        });
      },
    });
  }

  /** Route the user's review decisions to the pending approval pause. */
  submitDecisions(decisions: ApproveDecision[]): void {
    if (!this.pendingApproval) return;
    const resolve = this.pendingApproval.resolve;
    this.pendingApproval = undefined;
    resolve(decisions);
  }
}

export function sessionIdFor(projectName: string): string {
  const safe = projectName.replace(/[^a-zA-Z0-9_.-]/g, "-").slice(0, 128);
  return `latex-bridge-${safe}-${Date.now().toString(36)}`;
}
