import type { Proposal } from "../src/domain";

export class RealSuperDocsClient {
  private readonly baseUrl: string;
  constructor(
    private readonly apiKey: string,
    baseUrl: string,
  ) {
    if (!apiKey) throw new Error("SUPERDOCS_API_KEY is required");
    if (baseUrl !== "https://api.superdocs.app")
      throw new Error("SUPERDOCS_BASE_URL must be https://api.superdocs.app");
    this.baseUrl = baseUrl;
  }
  private async call(path: string, init: RequestInit = {}) {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
        ...init.headers,
      },
      signal: AbortSignal.timeout(60_000),
    });
    if (!response.ok)
      throw new Error(`SuperDocs ${path} failed with HTTP ${response.status}`);
    return response;
  }
  async upload(filename: string, content: string, existingSessionId?: string) {
    const sessionId = existingSessionId ?? `tax-memo-${crypto.randomUUID()}`;
    const response = await this.call("/v1/documents/upload-base64", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        filename,
        file_base64: Buffer.from(content).toString("base64"),
        return_html: false,
      }),
    });
    const body = (await response.json()) as Record<string, unknown>;
    return {
      sessionId,
      documentId: String(
        body.document_id ?? body.durable_document_id ?? "not_returned",
      ),
    };
  }
  async instruction(sessionId: string, message: string) {
    const response = await this.call("/v1/chat/async", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        message,
        approval_mode: "ask_every_time",
        response_mode: "compact",
      }),
    });
    const body = (await response.json()) as Record<string, unknown>;
    if (!body.job_id) throw new Error("SuperDocs chat response omitted job_id");
    return {
      jobId: String(body.job_id),
      status: String(body.status ?? "pending"),
    };
  }
  async poll(jobId: string) {
    const body = (await (
      await this.call(`/v1/jobs/${encodeURIComponent(jobId)}`)
    ).json()) as {
      status?: unknown;
      metadata?: { pending_changes?: unknown };
      result?: {
        document_changes?: { pending_changes?: unknown; chunk_diffs?: unknown };
      };
    };
    return {
      status: String(body.status),
      proposedChanges:
        body.metadata?.pending_changes ??
        body.result?.document_changes?.pending_changes ??
        body.result?.document_changes?.chunk_diffs,
    };
  }
  async approve(sessionId: string, jobId: string, changes: Proposal[]) {
    await this.call(`/v1/chat/${encodeURIComponent(sessionId)}/approve`, {
      method: "POST",
      body: JSON.stringify({
        job_id: jobId,
        approved: true,
        changes: changes.map((item) => ({
          change_id: item.id,
          approved: item.decision === "APPROVED",
          feedback: item.reviewerNote,
        })),
      }),
    });
  }
  async export(sessionId: string, format: "html") {
    const response = await this.call("/v1/documents/export", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        format,
        options: { filename: `tax-memo.${format}` },
      }),
    });
    return {
      format,
      bytes: new Uint8Array(await response.arrayBuffer()),
      contentType: response.headers.get("content-type"),
    };
  }
  async exportHtml(html: string, filename: string) {
    const response = await this.call("/v1/documents/export", {
      method: "POST",
      body: JSON.stringify({ html, format: "html", options: { filename } }),
    });
    return {
      bytes: new Uint8Array(await response.arrayBuffer()),
      contentType: response.headers.get("content-type"),
    };
  }
}
