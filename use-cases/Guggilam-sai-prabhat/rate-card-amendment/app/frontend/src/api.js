const BASE_URL = "http://127.0.0.1:8000";

function uuid() {
  return crypto.randomUUID();
}

async function parseJsonOrThrow(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail || {
      what: `request failed with status ${response.status}`,
      likely_cause: "unexpected response shape from the backend",
      next_action: "check the backend logs and retry",
    };
    const error = new Error(detail.what);
    error.detail = detail;
    throw error;
  }
  return body;
}

export async function createRun({ contracts, oldRateCard, newRateCard, effectiveDate, dryRun, idempotencyKey }) {
  const form = new FormData();
  contracts.forEach((file) => form.append("contracts", file));
  if (oldRateCard) form.append("old_rate_card", oldRateCard);
  form.append("new_rate_card", newRateCard);
  form.append("proposed_effective_date", effectiveDate);
  form.append("dry_run", dryRun ? "true" : "false");
  form.append("idempotency_key", idempotencyKey || uuid());

  const response = await fetch(`${BASE_URL}/runs`, { method: "POST", body: form });
  return parseJsonOrThrow(response);
}

export async function listCases(runId) {
  const response = await fetch(`${BASE_URL}/runs/${runId}/cases`);
  return parseJsonOrThrow(response);
}

export async function proposeCase(runId, caseId) {
  const response = await fetch(
    `${BASE_URL}/runs/${runId}/cases/${caseId}/propose?idempotency_key=${uuid()}`,
    { method: "POST" }
  );
  return parseJsonOrThrow(response);
}

export async function getReview(runId, caseId) {
  const response = await fetch(`${BASE_URL}/runs/${runId}/cases/${caseId}/review`);
  return parseJsonOrThrow(response);
}

export async function submitDecisions(runId, caseId, decisions) {
  const response = await fetch(`${BASE_URL}/runs/${runId}/cases/${caseId}/decisions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decisions, idempotency_key: uuid() }),
  });
  return parseJsonOrThrow(response);
}

export async function exportCase(runId, caseId, format = "markdown") {
  const response = await fetch(`${BASE_URL}/runs/${runId}/cases/${caseId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotency_key: uuid(), format }),
  });
  return parseJsonOrThrow(response);
}

export async function getControlReport(runId) {
  const response = await fetch(`${BASE_URL}/runs/${runId}/control-report`);
  return parseJsonOrThrow(response);
}

export { uuid };
