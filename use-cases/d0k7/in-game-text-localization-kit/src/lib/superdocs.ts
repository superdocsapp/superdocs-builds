type PendingChange = { change_id: string; operation: string; old_html: string | null; new_html: string | null; ai_explanation: string };
export type ReviewJob = { jobId: string; sessionId: string; changes: PendingChange[] };

const api = "/api/superdocs";

async function apiError(response: Response, action: string): Promise<never> {
  const detail = await response.text();
  throw new Error(`${action} failed: ${detail || response.statusText}`);
}

export async function startReview(sessionId: string, html: string): Promise<ReviewJob> {
  const response = await fetch(`${api}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId, html }),
  });
  if (!response.ok) return apiError(response, "Review request");
  const { job_id } = await response.json();
  for (;;) {
    await new Promise(resolve => setTimeout(resolve, 1500));
    const poll = await fetch(`${api}/jobs/${job_id}`);
    if (!poll.ok) return apiError(poll, "Review poll");
    const job = await poll.json();
    if (job.status === "failed") throw new Error(job.error ?? "SuperDocs job failed");
    if (job.status === "awaiting_approval") return { jobId: job_id, sessionId, changes: job.metadata?.pending_changes ?? [] };
    if (job.status === "completed") return { jobId: job_id, sessionId, changes: [] };
  }
}

export async function submitDecisions(review: ReviewJob, decisions: Record<string, boolean>): Promise<void> {
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
