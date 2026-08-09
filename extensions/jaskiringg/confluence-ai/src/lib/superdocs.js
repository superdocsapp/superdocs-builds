const DEFAULT_BASE = process.env.SUPERDOCS_API_BASE || "https://api.superdocs.app";

function parseJsonLenient(text) {
  if (text == null) return null;
  if (typeof text !== "string") return text;
  const cleaned = text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, " ");
  try {
    return JSON.parse(cleaned);
  } catch (err) {
    const once = cleaned.replace(/,\s*([}\]])/g, "$1");
    return JSON.parse(once);
  }
}

function parseTwice(value) {
  let v = value;
  if (typeof v === "string") v = parseJsonLenient(v);
  if (typeof v === "string") v = parseJsonLenient(v);
  return v;
}

function normalizePendingChanges(raw) {
  let v = parseTwice(raw);
  if (!v) return [];
  if (!Array.isArray(v) && v.changes) v = parseTwice(v.changes);
  if (!Array.isArray(v)) return [];
  return v.map((item) => {
    const c = typeof item === "string" ? parseTwice(item) : item;
    return c && typeof c === "object" ? c : null;
  }).filter(Boolean);
}

async function sdFetch(path, { method = "GET", body, apiKey, base = DEFAULT_BASE } = {}) {
  if (!apiKey) throw new Error("SUPERDOCS_API_KEY is missing");
  const res = await fetch(`${base}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? parseJsonLenient(text) : null;
  if (!res.ok) {
    const msg = data?.detail || data?.error || data?.message || text.slice(0, 400);
    const err = new Error(`SuperDocs ${res.status}: ${typeof msg === "string" ? msg : JSON.stringify(msg)}`);
    err.status = res.status;
    err.body = data;
    throw err;
  }
  return data;
}

async function startHitlEdit({ apiKey, sessionId, documentHtml, message, modelTier = "core" }) {
  return sdFetch("/v1/chat/async", {
    method: "POST",
    apiKey,
    body: {
      message,
      session_id: sessionId,
      document_html: documentHtml,
      approval_mode: "ask_every_time",
      model_tier: modelTier,
    },
  });
}

async function getJob({ apiKey, jobId }) {
  const job = await sdFetch(`/v1/jobs/${jobId}`, { apiKey });
  const pending = normalizePendingChanges(job?.metadata?.pending_changes);
  return { ...job, pending_changes: pending };
}

async function approveChanges({ apiKey, sessionId, jobId, decisions }) {
  const changes = decisions.map((d) => ({
    change_id: d.change_id,
    approved: !!d.approved,
    ...(d.feedback ? { feedback: d.feedback } : {}),
  }));
  return sdFetch(`/v1/chat/${encodeURIComponent(sessionId)}/approve`, {
    method: "POST",
    apiKey,
    body: {
      job_id: jobId,
      approved: true,
      changes,
    },
  });
}

async function continueJob({ apiKey, sessionId, jobId, shouldContinue }) {
  return sdFetch(`/v1/chat/${encodeURIComponent(sessionId)}/continue`, {
    method: "POST",
    apiKey,
    body: { job_id: jobId, continue: !!shouldContinue },
  });
}

async function exportPdf({ apiKey, sessionId, html, filename = "confluence-export" }) {
  const res = await fetch(`${DEFAULT_BASE}/v1/documents/export`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: html ? undefined : sessionId,
      html: html || undefined,
      format: "pdf",
      options: { filename, paper_size: "A4", margins: "normal" },
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Export failed ${res.status}: ${text.slice(0, 400)}`);
  }
  const buf = Buffer.from(await res.arrayBuffer());
  return {
    filename: `${filename}.pdf`,
    contentType: res.headers.get("content-type") || "application/pdf",
    base64: buf.toString("base64"),
    bytes: buf.length,
  };
}

const HOUSE_STRUCTURE_PROMPT = `Normalise this Confluence page to the house structure below.
Keep every fact that is already in the page. Do not invent owners, dates, metrics, or systems.
Do not rewrite or remove blocks marked as preserved (tables, code, macros).
Use these headings, in this order, and move existing sentences under the right heading:

# <keep the existing page title>
## Purpose
## Current status
## Decisions
## Open questions
## Next steps

If a heading has no supporting source text, write exactly: "Not stated in source."`;

const LETTERHEAD = `<div style="border-bottom:2px solid #172B4D;padding:0 0 10px;margin:0 0 18px;font-family:ui-sans-serif,system-ui,sans-serif">
  <div style="font-size:13px;letter-spacing:.04em;text-transform:uppercase;color:#44546F">Internal · implementation pack</div>
  <div style="font-size:18px;font-weight:700;color:#172B4D">House document export</div>
  <div style="font-size:12px;color:#626F86">Not for external distribution · generated via SuperDocs</div>
</div>`;

module.exports = {
  parseJsonLenient,
  parseTwice,
  normalizePendingChanges,
  startHitlEdit,
  getJob,
  approveChanges,
  continueJob,
  exportPdf,
  HOUSE_STRUCTURE_PROMPT,
  LETTERHEAD,
};
