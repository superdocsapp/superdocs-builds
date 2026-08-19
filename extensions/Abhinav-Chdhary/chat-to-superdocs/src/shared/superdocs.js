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

export function normalizeTemplateList(payload) {
  const candidates = Array.isArray(payload)
    ? payload
    : [payload?.templates, payload?.items, payload?.data].find(Array.isArray) ?? [];
  return candidates.map((template) => ({
    id: template.id ?? template.template_id,
    name: template.name ?? template.filename ?? template.file_name,
  })).filter((template) => typeof template.id === "string" && typeof template.name === "string");
}

export function normalizeSessionDocuments(payload) {
  const candidates = Array.isArray(payload)
    ? payload
    : [payload?.documents, payload?.items, payload?.data].find(Array.isArray) ?? [];
  return candidates.map((document) => ({
    id: document.id ?? document.document_id,
    durableId: document.durable_document_id ?? document.durableId ?? null,
    focused: Boolean(document.focused ?? document.is_focused),
  })).filter((document) => typeof document.id === "string");
}

export function focusedSessionDocument(payload) {
  const documents = normalizeSessionDocuments(payload);
  return documents.find((document) => document.focused) ?? documents[0] ?? null;
}

export function savedDocumentExists(payload, durableId) {
  const candidates = Array.isArray(payload)
    ? payload
    : [payload?.documents, payload?.items, payload?.data].find(Array.isArray) ?? [];
  return candidates.some((document) => (document.id ?? document.document_id) === durableId);
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
  constructor(baseUrl, extensionId = null) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.extensionId = extensionId;
  }

  async request(path, init = {}) {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...(this.extensionId ? { "x-chat-to-superdocs-origin": `chrome-extension://${this.extensionId}` } : {}),
        ...(init.headers ?? {}),
      },
    });
    if (!response.ok) throw new Error(await response.text() || `Bridge request failed (${response.status}).`);
    return response;
  }

  async startJob(payload) {
    return (await this.request("/api/jobs", { method: "POST", body: JSON.stringify(payload) })).json();
  }

  async listTemplates() {
    const payload = await (await this.request("/api/templates")).json();
    return normalizeTemplateList(payload);
  }

  async openBlankDocument(sessionId) {
    return (await this.request(`/api/sessions/${encodeURIComponent(sessionId)}/documents/blank`, { method: "POST", body: "{}" })).json();
  }

  async listSessionDocuments(sessionId) {
    return (await this.request(`/api/sessions/${encodeURIComponent(sessionId)}/documents`)).json();
  }

  async saveDocument(sessionId, documentId, html) {
    return (await this.request(`/api/sessions/${encodeURIComponent(sessionId)}/documents/${encodeURIComponent(documentId)}/save`, { method: "POST", body: JSON.stringify({ html }) })).json();
  }

  async listDocuments() {
    return (await this.request("/api/documents")).json();
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
