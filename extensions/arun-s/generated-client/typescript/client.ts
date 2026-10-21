// SuperDocs client (TypeScript) — the four core calls, mirroring the validated
// Python client. Behaviour is pinned by the shared conformance scenarios.
export interface Job { job_id: string; status: string; metadata?: any; }

export class SuperDocs {
  private base: string;
  constructor(baseUrl: string, private apiKey: string) { this.base = baseUrl.replace(/\/$/, ""); }

  private async req(method: string, path: string, body?: unknown): Promise<Response> {
    const r = await fetch(this.base + path, {
      method,
      headers: { Authorization: `Bearer ${this.apiKey}`, "content-type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r;
  }

  chatAsync(message: string, sessionId: string,
            o: { documentHtml?: string; approvalMode?: string; modelTier?: string; responseMode?: string } = {}) {
    return this.req("POST", "/v1/chat/async", {
      message, session_id: sessionId, response_mode: o.responseMode ?? "compact",
      ...(o.documentHtml ? { document_html: o.documentHtml } : {}),
      ...(o.approvalMode ? { approval_mode: o.approvalMode } : {}),
      ...(o.modelTier ? { model_tier: o.modelTier } : {}),
    }).then((r) => r.json() as Promise<Job>);
  }
  getJob(jobId: string) { return this.req("GET", `/v1/jobs/${jobId}`).then((r) => r.json() as Promise<Job>); }
  approve(sessionId: string, jobId: string, changes: { change_id: string; approved: boolean }[]) {
    // AMBIGUITIES #3: job_id + change_id (never chunk_id)
    return this.req("POST", `/v1/chat/${sessionId}/approve`, { job_id: jobId, approved: true, changes }).then((r) => r.json());
  }
  export(sessionId: string, format = "docx") {
    return this.req("POST", "/v1/documents/export", { session_id: sessionId, format }).then((r) => r.arrayBuffer());
  }
  // AMBIGUITIES #1: proposed-change content is a JSON-encoded string (second parse)
  static parseProposedChange(content: string) { return typeof content === "string" ? JSON.parse(content) : content; }
}
