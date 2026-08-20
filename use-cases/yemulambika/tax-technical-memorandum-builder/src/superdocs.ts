import type { Proposal } from "./domain";

export type UploadResult = { sessionId: string; documentId: string };
export type ChatResult = { jobId: string; status: string };
export type ExportResult = { format: string; bytes: Uint8Array };
export interface SuperDocsClient {
  upload(filename: string, content: string): Promise<UploadResult>;
  instruction(sessionId: string, message: string): Promise<ChatResult>;
  poll(jobId: string): Promise<{ status: string; proposedChanges?: unknown }>;
  approve(sessionId: string, jobId: string, changes: Proposal[]): Promise<void>;
  export(sessionId: string, format: "html"): Promise<ExportResult>;
}
export class SuperDocsError extends Error {
  constructor(
    message: string,
    public action: string,
    public status?: number,
  ) {
    super(message);
  }
}
export class FakeSuperDocsClient implements SuperDocsClient {
  approved: Proposal[] = [];
  async upload(_filename: string, _content: string) {
    return { sessionId: "fake-session", documentId: "fake-document" };
  }
  async instruction(_sessionId: string, _message: string) {
    return { jobId: "fake-job", status: "awaiting_approval" };
  }
  async poll(_jobId: string) {
    return {
      status: "awaiting_approval",
      proposedChanges: JSON.stringify([
        {
          change_id: "fixture-change-valid",
          section: "Analysis",
          before: "",
          after: "INR 1200000 taxable amount is supported.",
        },
        {
          change_id: "fixture-change-fabricated",
          section: "Analysis",
          before: "",
          after: "Every fictional disposal is automatically exempt from tax.",
        },
      ]),
    };
  }
  async approve(_s: string, _j: string, changes: Proposal[]) {
    this.approved = changes.filter((x) => x.decision === "APPROVED");
  }
  async export(_s: string, format: "html") {
    return {
      format,
      bytes: new TextEncoder().encode("FAKE EXPORT — not live evidence"),
    };
  }
}

/** Browser client: credentials are held by the same-origin Node BFF only. */
export class BffSuperDocsClient implements SuperDocsClient {
  private async call(path: string, init: RequestInit = {}) {
    const response = await fetch(`/api/superdocs${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as {
        error?: string;
      };
      throw new SuperDocsError(
        body.error ?? `Request failed with HTTP ${response.status}`,
        path,
        response.status,
      );
    }
    return response;
  }
  async upload(filename: string, content: string) {
    return (await (
      await this.call("/upload", {
        method: "POST",
        body: JSON.stringify({ filename, content }),
      })
    ).json()) as UploadResult;
  }
  async instruction(sessionId: string, message: string) {
    return (await (
      await this.call("/chat", {
        method: "POST",
        body: JSON.stringify({ sessionId, message }),
      })
    ).json()) as ChatResult;
  }
  async poll(jobId: string) {
    return (await (
      await this.call(`/jobs/${encodeURIComponent(jobId)}`)
    ).json()) as { status: string; proposedChanges?: unknown };
  }
  async approve(sessionId: string, jobId: string, changes: Proposal[]) {
    await this.call(`/chat/${encodeURIComponent(sessionId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ jobId, changes }),
    });
  }
  async export(sessionId: string, format: "html") {
    const response = await this.call("/export", {
      method: "POST",
      body: JSON.stringify({ sessionId, format }),
    });
    return { format, bytes: new Uint8Array(await response.arrayBuffer()) };
  }
}
export async function pollBounded(
  client: SuperDocsClient,
  jobId: string,
  max = 30,
  delay = 1000,
) {
  for (let i = 0; i < max; i++) {
    const state = await client.poll(jobId);
    if (["awaiting_approval", "completed"].includes(state.status)) return state;
    if (["failed", "cancelled"].includes(state.status))
      throw new SuperDocsError(
        `SuperDocs job ended with status ${state.status}`,
        "poll",
      );
    await new Promise((resolve) =>
      setTimeout(resolve, Math.min(delay * 2 ** i, 8000)),
    );
  }
  throw new SuperDocsError(
    `SuperDocs operation timed out after ${max} polls`,
    "poll",
  );
}
