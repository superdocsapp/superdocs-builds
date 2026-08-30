import { randomUUID } from "node:crypto";
import { SuperDocsClient, type ApproveDecision, type JobResult, type UploadResult, type SuperDocsModelTier, type SuperDocsThinkingDepth } from "./client.js";

export interface SuperDocsRunState {
  status: "not_started" | "uploaded" | "processing" | "awaiting_approval" | "completed" | "failed";
  sessionId: string | null;
  jobId: string | null;
  versionId: string | null;
  pendingChanges: Array<Record<string, unknown>>;
  updatedHtml: string | null;
  lastError: string | null;
  lastActionAt: string | null;
}

export function emptySuperDocsState(): SuperDocsRunState {
  return { status: "not_started", sessionId: null, jobId: null, versionId: null, pendingChanges: [], updatedHtml: null, lastError: null, lastActionAt: null };
}

function stateAction(state: SuperDocsRunState, patch: Partial<SuperDocsRunState>): SuperDocsRunState {
  return { ...state, ...patch, lastActionAt: new Date().toISOString(), lastError: null };
}

export class SuperDocsIntegration {
  constructor(private readonly client = new SuperDocsClient()) {}

  async probe(): Promise<{ authenticated: boolean; status: number }> {
    return this.client.probeAuth();
  }

  async prepareDocument(state: SuperDocsRunState, html: string, filename: string, instruction: string, options: { modelTier?: SuperDocsModelTier; thinkingDepth?: SuperDocsThinkingDepth } = {}): Promise<SuperDocsRunState> {
    if (state.status === "processing" || state.status === "awaiting_approval" || state.status === "completed") return state;
    let upload: UploadResult | null = null;
    try {
      // Keep the explicit upload step required by the use-case when the API
      // exposes it. If a deployment has moved to the HTML-first contract, the
      // fallback below still gives the same reviewable workflow.
      upload = await this.client.uploadDocument(new Blob([html], { type: "text/html" }), filename);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (!message.includes("404")) {
        return stateAction(state, { status: "failed", lastError: message });
      }
    }

    const sessionId = upload?.sessionId ?? `translation-${randomUUID()}`;
    const next = stateAction(state, { status: "processing", sessionId, versionId: upload?.versionId ?? null });
    try {
      const job = await this.client.chatAsync({
        message: instruction,
        sessionId,
        documentHtml: html,
        approvalMode: "ask_every_time",
        modelTier: options.modelTier ?? (process.env.SUPERDOCS_MODEL_TIER as SuperDocsModelTier | undefined),
        thinkingDepth: options.thinkingDepth ?? (process.env.SUPERDOCS_THINKING_DEPTH as SuperDocsThinkingDepth | undefined),
      });
      const settled = await this.client.pollJobUntilSettled(job.jobId);
      return stateAction(next, {
        status: settled.status === "awaiting_approval" ? "awaiting_approval" : settled.status === "completed" ? "completed" : settled.status === "failed" || settled.status === "cancelled" ? "failed" : "processing",
        jobId: settled.jobId,
        pendingChanges: settled.pendingChanges,
        updatedHtml: settled.updatedHtml,
        lastError: settled.status === "failed" ? "SuperDocs reported a failed job." : null,
      });
    } catch (error) {
      return stateAction(next, { status: "failed", lastError: error instanceof Error ? error.message : String(error) });
    }
  }

  async refreshJob(state: SuperDocsRunState): Promise<SuperDocsRunState> {
    if (!state.jobId) throw new Error("No SuperDocs job is associated with this run.");
    try {
      const settled: JobResult = await this.client.getJob(state.jobId);
      return stateAction(state, {
        status: settled.status === "awaiting_approval" ? "awaiting_approval" : settled.status === "completed" ? "completed" : settled.status === "failed" || settled.status === "cancelled" ? "failed" : "processing",
        pendingChanges: settled.pendingChanges,
        updatedHtml: settled.updatedHtml,
      });
    } catch (error) {
      return stateAction(state, { status: "failed", lastError: error instanceof Error ? error.message : String(error) });
    }
  }

  async approve(state: SuperDocsRunState, decisions: ApproveDecision[]): Promise<SuperDocsRunState> {
    if (!state.sessionId) throw new Error("No SuperDocs session is associated with this run.");
    try {
      await this.client.approveChanges(state.sessionId, decisions);
      const refreshed = state.jobId ? await this.client.getJob(state.jobId) : null;
      return stateAction(state, {
        status: refreshed?.status === "completed" ? "completed" : "processing",
        pendingChanges: refreshed?.pendingChanges ?? [],
        updatedHtml: refreshed?.updatedHtml ?? state.updatedHtml,
      });
    } catch (error) {
      return stateAction(state, { status: "failed", lastError: error instanceof Error ? error.message : String(error) });
    }
  }

  async exportDocx(state: SuperDocsRunState): Promise<Blob> {
    if (!state.sessionId) throw new Error("No SuperDocs session is associated with this run.");
    return this.client.exportDocument({ sessionId: state.sessionId, format: "docx" });
  }
}
