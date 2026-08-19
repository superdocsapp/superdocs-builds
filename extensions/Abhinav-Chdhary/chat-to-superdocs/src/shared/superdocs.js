const PROCESSING = new Set(["pending", "in_progress"]);
const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export function parseProposedChangeBatch(eventData) {
  const envelope = JSON.parse(eventData);
  if (typeof envelope.content !== "string") {
    throw new Error("Expected proposed-change content to be a JSON string.");
  }
  const batch = JSON.parse(envelope.content);
  if (!Array.isArray(batch.changes)) {
    throw new Error("The proposed-change batch did not contain changes.");
  }
  return batch.changes;
}

export function jobState(job) {
  if (PROCESSING.has(job.status)) return "processing";
  if (job.status === "awaiting_approval") return "review";
  if (TERMINAL.has(job.status)) return job.status;
  return "unknown";
}

export function pendingChanges(job) {
  const changes = job?.metadata?.pending_changes;
  return Array.isArray(changes) ? changes : [];
}

export function finalHtml(job) {
  return job?.result?.document_changes?.updated_html
    ?? job?.metadata?.document_html
    ?? job?.document_changes?.updated_html
    ?? null;
}

export function decisionsFromForm(changes, selectedIds) {
  return changes.map((change) => ({
    change_id: change.change_id,
    approved: selectedIds.has(change.change_id),
  }));
}

export class BridgeClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async request(path, init = {}) {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
    });
    if (!response.ok) throw new Error(await response.text() || `Bridge request failed (${response.status}).`);
    return response;
  }

  async startJob(payload) {
    return (await this.request("/api/jobs", { method: "POST", body: JSON.stringify(payload) })).json();
  }

  async getJob(jobId) {
    return (await this.request(`/api/jobs/${encodeURIComponent(jobId)}`)).json();
  }

  async decide(sessionId, payload) {
    return (await this.request(`/api/sessions/${encodeURIComponent(sessionId)}/approve`, { method: "POST", body: JSON.stringify(payload) })).json();
  }

  async exportDocument(payload) {
    return this.request("/api/export", { method: "POST", body: JSON.stringify(payload) });
  }
}
