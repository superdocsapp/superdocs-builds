export type PendingChange = { change_id: string; operation: string; old_html: string | null; new_html: string | null; ai_explanation: string };
export type ReviewJob = { jobId: string; sessionId: string; changes: PendingChange[]; updatedHtml: string | null };
type JsonRecord = Record<string, unknown>;

const api = "/api/superdocs";

async function apiError(response: Response, action: string): Promise<never> {
  const detail = await response.text();
  throw new Error(`${action} failed: ${detail || response.statusText}`);
}

function record(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as JsonRecord : null;
}

function decodeJson(value: unknown): unknown {
  let decoded = value;
  for (let pass = 0; pass < 2 && typeof decoded === "string"; pass += 1) decoded = JSON.parse(decoded);
  return decoded;
}

function pendingChange(value: unknown): PendingChange | null {
  const item = record(decodeJson(value));
  if (!item || typeof item.change_id !== "string" || typeof item.operation !== "string" || typeof item.ai_explanation !== "string") return null;
  return {
    change_id: item.change_id,
    operation: item.operation,
    old_html: typeof item.old_html === "string" ? item.old_html : null,
    new_html: typeof item.new_html === "string" ? item.new_html : null,
    ai_explanation: item.ai_explanation,
  };
}

export function parsePendingChanges(metadata: unknown): PendingChange[] {
  const encodedChanges = record(metadata)?.pending_changes;
  const decoded = decodeJson(encodedChanges);
  const values = Array.isArray(decoded) ? decoded : decoded === undefined || decoded === null ? [] : [decoded];
  return values.map(pendingChange).filter((change): change is PendingChange => change !== null);
}

function updatedHtml(payload: unknown): string | null {
  const root = record(payload);
  if (!root) return null;
  const candidates = [root.document_changes, root.result, record(root.result)?.document_changes, root.metadata, record(root.metadata)?.document_changes];
  for (const candidate of candidates) {
    const value = record(candidate)?.updated_html;
    if (typeof value === "string" && value.trim()) return value;
  }
  return null;
}

async function pollJob(jobId: string, action: string): Promise<unknown> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    await new Promise(resolve => setTimeout(resolve, 1500));
    const poll = await fetch(`${api}/jobs/${jobId}`);
    if (!poll.ok) return apiError(poll, action);
    const job: unknown = await poll.json();
    const jobRecord = record(job);
    if (jobRecord?.status === "failed") throw new Error(typeof jobRecord.error === "string" ? jobRecord.error : "SuperDocs job failed");
    if (jobRecord?.status === "awaiting_approval" || jobRecord?.status === "completed") return job;
  }
  throw new Error("SuperDocs review timed out after three minutes. Check the job again before retrying.");
}

export async function startReview(sessionId: string, html: string): Promise<ReviewJob> {
  const response = await fetch(`${api}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId, html }),
  });
  if (!response.ok) return apiError(response, "Review request");
  const result: unknown = await response.json();
  const jobId = record(result)?.job_id;
  if (typeof jobId !== "string" || !jobId) throw new Error("SuperDocs did not return a job ID.");
  const job = await pollJob(jobId, "Review poll");
  return { jobId, sessionId, changes: parsePendingChanges(record(job)?.metadata), updatedHtml: updatedHtml(job) };
}

export async function submitDecisions(review: ReviewJob, decisions: Record<string, boolean>): Promise<string | null> {
  const response = await fetch(`${api}/approvals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sessionId: review.sessionId,
      jobId: review.jobId,
      changes: review.changes.map(change => ({ change_id: change.change_id, approved: decisions[change.change_id] })),
    }),
  });
  if (!response.ok) return apiError(response, "Approval");
  const approvalResult: unknown = await response.json();
  const immediateHtml = updatedHtml(approvalResult);
  if (immediateHtml) return immediateHtml;
  return updatedHtml(await pollJob(review.jobId, "Approval completion poll"));
}

export async function exportKit(sessionId: string): Promise<void> {
  const response = await fetch(`${api}/exports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId }),
  });
  if (!response.ok) return apiError(response, "Export");
  const url = URL.createObjectURL(await response.blob());
  const link = Object.assign(document.createElement("a"), { href: url, download: "localization-kit.docx" });
  link.click();
  URL.revokeObjectURL(url);
}
