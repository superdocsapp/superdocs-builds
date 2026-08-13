import { normalizePollingPayload } from "./normalizers";
import { MemoryRunStateStore, type RunStateStore } from "./state";
import type {
  ApprovalDecision,
  ApprovalPayload,
  NormalizedJob,
  PendingChange,
  SuperDocsPort,
  WriterPort,
} from "./types";

export type Stage =
  | "reading"
  | "uploading"
  | "asking"
  | "polling"
  | "review"
  | "approving"
  | "continuing"
  | "exporting"
  | "complete"
  | "error";

export interface WorkflowEvent {
  stage: Stage;
  message: string;
  job?: NormalizedJob;
}

export interface PollOptions {
  intervalMs?: number;
  timeoutMs?: number;
  maxConsecutiveErrors?: number;
}

export const buildApprovalPayload = (
  jobId: string,
  decisions: ApprovalDecision[],
): ApprovalPayload => ({
  job_id: jobId,
  approved: decisions.every((decision) => decision.approved),
  changes: decisions.map((decision) => ({
    change_id: decision.changeId,
    approved: decision.approved,
    ...(decision.feedback ? { feedback: decision.feedback } : {}),
  })),
});

export const getHostWritebackBlock = (changes: PendingChange[]): string => {
  const structural = changes.find(
    (change) =>
      change.operation === "create" ||
      change.operation === "delete" ||
      change.insertAfterChunkId !== undefined,
  );
  if (structural) {
    return `Host writeback is unavailable: structural change ${structural.id} (${structural.operation}) requires a verified chunk/range API.`;
  }
  return "Host writeback is disabled until live Sigma testing verifies a selection-replacement capability. SuperDocs structural HTML is review data and is never substring-mapped onto Zoho HTML.";
};

const sleep = (milliseconds: number) =>
  new Promise<void>((resolve) => globalThis.setTimeout(resolve, milliseconds));

export class ReviewWorkflow {
  private activeSessionId?: string;
  private activeJobId?: string;
  private activeAwaitingKind?: string;

  constructor(
    private readonly writer: WriterPort,
    private readonly api: SuperDocsPort,
    private readonly emit: (event: WorkflowEvent) => void = () => undefined,
    private readonly pollOptions: PollOptions = {},
    private readonly stateStore: RunStateStore = new MemoryRunStateStore(),
  ) {}

  canResume(): boolean {
    return Boolean(this.activeSessionId && this.activeJobId);
  }

  getActiveContext(): {
    sessionId?: string;
    jobId?: string;
    awaitingKind?: string;
  } {
    return {
      sessionId: this.activeSessionId,
      jobId: this.activeJobId,
      awaitingKind: this.activeAwaitingKind,
    };
  }

  async begin(instruction: string): Promise<{
    sessionId: string;
    job: NormalizedJob;
  }> {
    this.emit({ stage: "reading", message: "Reading the current selection…" });
    const originalHtml = await this.writer.getSelectedHtml();
    if (!originalHtml.trim()) {
      throw new Error("Select a specific passage in Writer before starting.");
    }

    this.stateStore.clear();
    const sessionId = `zoho_${crypto.randomUUID()}`;
    this.activeSessionId = sessionId;
    this.activeJobId = undefined;
    this.activeAwaitingKind = undefined;
    this.emit({ stage: "uploading", message: "Uploading selected HTML securely…" });
    await this.api.upload(originalHtml, sessionId);

    this.emit({ stage: "asking", message: "Starting an approval-gated edit…" });
    const started = normalizePollingPayload(
      await this.api.startChat(sessionId, instruction),
    );
    if (!started.jobId) throw new Error("SuperDocs did not return a job ID.");
    this.activeJobId = started.jobId;
    this.stateStore.save({
      version: 1,
      sessionId,
      jobId: started.jobId,
      status: "pending",
    });

    const job = await this.pollToGate(started.jobId);
    return { sessionId, job };
  }

  async restore(): Promise<NormalizedJob | null> {
    const saved = this.stateStore.load();
    if (!saved) return null;
    this.activeSessionId = saved.sessionId;
    this.activeJobId = saved.jobId;
    this.activeAwaitingKind = saved.awaitingKind;
    this.emit({
      stage: saved.status === "awaiting_approval" ? "review" : "polling",
      message:
        saved.awaitingKind === "continue_prompt"
          ? "Restoring the existing continue prompt…"
          : "Restoring the existing SuperDocs job…",
    });
    return this.pollToGate(saved.jobId);
  }

  async resume(): Promise<NormalizedJob> {
    if (!this.activeSessionId || !this.activeJobId) {
      throw new Error(
        "No existing job can be resumed. Starting again would create a new run.",
      );
    }
    this.emit({ stage: "polling", message: "Resuming the existing job…" });
    return this.pollToGate(this.activeJobId);
  }

  async decideRound(
    sessionId: string,
    jobId: string,
    decisions: ApprovalDecision[],
  ): Promise<NormalizedJob> {
    if (decisions.length === 0) {
      throw new Error("Every proposed change needs an accept or reject decision.");
    }
    this.emit({ stage: "approving", message: "Submitting item-level decisions…" });
    await this.api.approve(sessionId, buildApprovalPayload(jobId, decisions));
    return this.pollToGate(jobId);
  }

  async continueRound(
    sessionId: string,
    jobId: string,
    shouldContinue: boolean,
  ): Promise<NormalizedJob> {
    this.emit({
      stage: "continuing",
      message: shouldContinue
        ? "Continuing the existing edit…"
        : "Stopping the existing edit safely…",
    });
    await this.api.continueChat(sessionId, jobId, shouldContinue);
    return this.pollToGate(jobId);
  }

  async export(sessionId: string): Promise<Blob> {
    this.emit({ stage: "exporting", message: "Exporting the approved DOCX…" });
    return this.api.exportDocument(sessionId);
  }

  private async pollToGate(
    jobId: string,
    options: PollOptions = this.pollOptions,
  ): Promise<NormalizedJob> {
    const intervalMs = options.intervalMs ?? 1500;
    const timeoutMs = options.timeoutMs ?? 5 * 60_000;
    const maxConsecutiveErrors = options.maxConsecutiveErrors ?? 3;
    const deadline = Date.now() + timeoutMs;
    let errors = 0;

    while (Date.now() < deadline) {
      let job: NormalizedJob;
      try {
        job = normalizePollingPayload(await this.api.getJob(jobId));
        errors = 0;
      } catch (error) {
        errors += 1;
        if (errors > maxConsecutiveErrors) throw error;
        this.emit({
          stage: "polling",
          message: `Temporary polling error; retrying (${errors}/${maxConsecutiveErrors})…`,
        });
        await sleep(intervalMs);
        continue;
      }

      this.emit({
        stage: job.status === "awaiting_approval" ? "review" : "polling",
        message:
          job.status === "awaiting_approval"
            ? job.awaitingKind === "continue_prompt"
              ? "SuperDocs needs a continue or stop decision."
              : "Review each proposed change."
            : `Processing${job.progress === undefined ? "…" : ` — ${job.progress}%`}`,
        job,
      });
      if (job.status === "awaiting_approval" || job.status === "completed") {
        this.persistJobState(job);
        return job;
      }
      if (job.status === "failed" || job.status === "cancelled") {
        this.stateStore.clear();
        this.activeJobId = undefined;
        this.activeAwaitingKind = undefined;
        throw new Error(job.error ?? `Job ${job.status}.`);
      }
      this.persistJobState(job);
      await sleep(intervalMs);
    }
    throw new Error("The job is still processing after five minutes. Retry polling.");
  }

  private persistJobState(job: NormalizedJob): void {
    if (!this.activeSessionId || !this.activeJobId) return;
    if (job.status === "completed") {
      this.stateStore.clear();
      this.activeJobId = undefined;
      this.activeAwaitingKind = undefined;
      return;
    }
    if (
      job.status !== "pending" &&
      job.status !== "in_progress" &&
      job.status !== "awaiting_approval"
    ) {
      return;
    }
    this.activeAwaitingKind = job.awaitingKind;
    this.stateStore.save({
      version: 1,
      sessionId: this.activeSessionId,
      jobId: this.activeJobId,
      status: job.status,
      ...(job.awaitingKind ? { awaitingKind: job.awaitingKind } : {}),
    });
  }
}
