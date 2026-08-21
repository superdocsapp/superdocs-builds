/** What happened to an approved fix, as opposed to what the human decided. */
export type ApplyStatus =
  | "queued"
  | "applying"
  | "applied"
  | "blocked"
  | "failed"
  /** The document is gone from SuperDocs; retrying cannot help, re-ingest can. */
  | "document_missing";

export interface Finding {
  id: string;
  state: "CONFIRMED_DRIFT" | "NO_DRIFT" | "UNKNOWN";
  chunk_id: string;
  evidence_quote: string;
  evidence_chunk_id: string;
  proposed_old: string;
  proposed_new: string;
  ai_explanation: string;
  document_id: string;
  filename: string;
  review_decision?: string;
  review_feedback?: string;
  apply_status?: ApplyStatus | null;
  apply_reason?: string | null;
  applied_at?: string | null;
}

export interface RunStatus {
  run_id: string;
  findings: Finding[];
}

export interface CostStage {
  node: string;
  steps: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_superdocs_ops: number;
  total_ms: number;
}

export interface CostReport {
  run_id: string;
  stages: CostStage[];
  total_ops: number;
}

export interface RunSummary {
  id: string;
  corpus_ref: string | null;
  feed_ref: string | null;
  trigger: string;
  status: string;
  created_at: string;
}

export interface DocumentSummary {
  id: string;
  run_id: string;
  filename: string;
  file_hash: string;
  session_id: string;
  superdocs_doc_id: string | null;
  created_at: string;
  chunk_count: number;
}

export interface UploadResult {
  run_id: string;
  document_ids: string[];
  filenames: string[];
  job_id: string | null;
}

// Ingestor API (Agent #1): runs, upload, document view/download/delete
const INGESTOR_BASE = import.meta.env.VITE_INGESTOR_API_URL || "http://localhost:8001";
// Editor / Review API (Agent #3): review, approve/reject, apply, export
const EDITOR_BASE = import.meta.env.VITE_EDITOR_API_URL || "http://localhost:8003";
// Analyzer API (Agent #2): findings, run status, cost
const ANALYZER_BASE = import.meta.env.VITE_ANALYZER_API_URL || "http://localhost:8002";

async function fetchJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

export async function listRuns(): Promise<{ runs: RunSummary[] }> {
  return fetchJson(`${INGESTOR_BASE}/runs`);
}

export async function listDocuments(runId?: string): Promise<{ documents: DocumentSummary[] }> {
  const url = runId
    ? `${INGESTOR_BASE}/documents?run_id=${encodeURIComponent(runId)}`
    : `${INGESTOR_BASE}/documents`;
  return fetchJson(url);
}

export async function uploadDocuments(files: File[], runId?: string): Promise<UploadResult> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  if (runId) form.append("run_id", runId);
  const r = await fetch(`${INGESTOR_BASE}/upload`, { method: "POST", body: form });
  if (!r.ok) throw new Error(`Upload failed: ${r.status}`);
  return r.json();
}

export function documentContentUrl(
  documentId: string,
  mode: "inline" | "attachment" = "inline",
  format: "html" | "text" = "html"
): string {
  return `${INGESTOR_BASE}/documents/${documentId}/content?disposition=${mode}&format=${format}`;
}

export async function getDocumentText(documentId: string): Promise<string> {
  const r = await fetch(documentContentUrl(documentId, "inline"));
  if (!r.ok) throw new Error(`Document fetch failed: ${r.status}`);
  const html = await r.text();
  // Best-effort plain-text view of the chunked HTML for highlighting.
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

export interface DocumentEdit {
  id: string;
  chunk_id: string | null;
  before_html: string | null;
  after_html: string | null;
  before_hash: string | null;
  after_hash: string | null;
  proposed_old: string | null;
  proposed_new: string | null;
  superdocs_job_id: string | null;
  superdocs_change_id: string | null;
  applied_at: string;
  finding_id: string;
  run_id: string | null;
  evidence_quote: string | null;
  ai_explanation: string | null;
  review_decision: string | null;
  review_feedback: string | null;
  decided_at: string | null;
}

export interface PendingEdit {
  finding_id: string;
  run_id: string | null;
  chunk_id: string | null;
  evidence_chunk_id: string | null;
  proposed_old: string | null;
  proposed_new: string | null;
  apply_status: ApplyStatus | null;
  apply_reason: string | null;
  ai_explanation: string | null;
  review_decision: string | null;
  decided_at: string | null;
}

export interface DocumentHistory {
  document_id: string;
  filename: string;
  edits: DocumentEdit[];
  pending: PendingEdit[];
}

export async function getDocumentHistory(documentId: string): Promise<DocumentHistory> {
  return fetchJson<DocumentHistory>(`${INGESTOR_BASE}/documents/${documentId}/history`);
}

export interface ReingestResult {
  document_id: string;
  filename: string;
  previous_superdocs_doc_id: string | null;
  superdocs_doc_id: string;
  session_id: string;
  chunks: number;
}

/** Rebuild a document's SuperDocs identity from its original file. */
export async function reingestDocument(documentId: string): Promise<ReingestResult> {
  const r = await fetch(`${INGESTOR_BASE}/documents/${documentId}/reingest`, {
    method: "POST",
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${r.status}: ${body.slice(0, 300)}`);
  }
  return r.json();
}

export async function deleteDocument(documentId: string): Promise<void> {
  const r = await fetch(`${INGESTOR_BASE}/documents/${documentId}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`Delete failed: ${r.status}`);
}

export async function getFindings(runId: string): Promise<RunStatus> {
  return fetchJson<RunStatus>(`${EDITOR_BASE}/review/${runId}`);
}

// These deliberately check r.ok. They used to ignore the response entirely, so
// a rejected approval looked identical to an accepted one and the UI happily
// reported success for a decision the server never recorded.
async function postDecision(url: string, feedback?: string): Promise<Record<string, unknown>> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback: feedback || "" }),
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${r.status}: ${body.slice(0, 200)}`);
  }
  return r.json();
}

export async function approveFinding(
  findingId: string,
  feedback?: string
): Promise<{ apply_status?: ApplyStatus }> {
  return postDecision(`${EDITOR_BASE}/review/${findingId}/approve`, feedback) as Promise<{
    apply_status?: ApplyStatus;
  }>;
}

export async function rejectFinding(findingId: string, feedback?: string): Promise<void> {
  await postDecision(`${EDITOR_BASE}/review/${findingId}/reject`, feedback);
}

export async function getCost(runId: string): Promise<CostReport> {
  return fetchJson<CostReport>(`${ANALYZER_BASE}/run/${runId}/cost`);
}

export interface TraceEntry {
  id: string;
  node: string;
  input_hash: string;
  decision: string | null;
  evidence: Record<string, unknown> | null;
  tokens_in: number | null;
  tokens_out: number | null;
  superdocs_ops: number;
  ms: number;
  ts: string;
}

export interface StepEntry {
  node: string;
  input_hash: string;
  status: string;
  output_ref: Record<string, unknown> | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface RunLogs {
  run: RunSummary;
  trace: TraceEntry[];
  steps: StepEntry[];
}

export async function getRunLogs(runId: string): Promise<RunLogs> {
  return fetchJson<RunLogs>(`${ANALYZER_BASE}/run/${runId}/logs`);
}

export async function stopRun(runId: string): Promise<{ status: string }> {
  const r = await fetch(`${ANALYZER_BASE}/run/${runId}/stop`, { method: "POST" });
  if (!r.ok) throw new Error(`Stop failed: ${r.status}`);
  return r.json();
}

export async function resumeRun(
  runId: string
): Promise<{ status: string; resumed_from_completed_steps: number }> {
  const r = await fetch(`${ANALYZER_BASE}/run/${runId}/resume`, { method: "POST" });
  if (!r.ok) throw new Error(`Resume failed: ${r.status}`);
  return r.json();
}

export interface ApplyResult {
  finding_id: string;
  status: "APPLIED" | "NEEDS_ESCALATION" | "ALARM" | "FAILED" | "ALREADY_APPLIED";
  reason?: string;
  phase?: string;
  target_chunk_changed?: boolean;
  chunks_verified?: number;
  /** Set when the document itself is gone: re-ingest, do not retry. */
  document_missing?: boolean;
}

export async function applyApproved(
  runId: string
): Promise<{ considered: number; counts: Record<string, number>; items: ApplyResult[] }> {
  const r = await fetch(`${EDITOR_BASE}/apply/${runId}`, { method: "POST" });
  if (!r.ok) throw new Error(`Apply failed: ${r.status}`);
  return r.json();
}

export async function applyFinding(findingId: string): Promise<ApplyResult> {
  const r = await fetch(`${EDITOR_BASE}/apply/finding/${findingId}`, { method: "POST" });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`Apply failed (${r.status}): ${body.slice(0, 200)}`);
  }
  return r.json();
}

export interface RunMetrics {
  run_id: string;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  true_negatives: number;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  accuracy: number | null;
  committed: number;
  unknown: number;
  total_findings: number;
  coverage: number | null;
  unknown_rate: number | null;
  scored_facts: number;
  unscorable_facts: number;
  method: string;
  limitations: string[];
}

export async function getMetrics(runId: string): Promise<RunMetrics> {
  return fetchJson<RunMetrics>(`${ANALYZER_BASE}/run/${runId}/metrics`);
}

export async function getExportUrl(runId: string): Promise<{ download_url: string }> {
  return fetchJson(`${EDITOR_BASE}/export/${runId}`);
}

/** Offsets rather than pre-highlighted markup, so document text can never
 *  inject markup into the results list. */
export interface SearchSnippet {
  text: string;
  match_start: number;
  match_length: number;
}

export interface SearchHit {
  chunk_row_id: string;
  chunk_id: string;
  document_id: string;
  filename: string;
  run_id: string;
  /** "exact" contains the query verbatim; "semantic" is a nearby meaning. */
  match_type: "exact" | "semantic";
  occurrences: number;
  matched_text: string | null;
  similarity?: number;
  snippet: SearchSnippet;
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchHit[];
  exact_count: number;
  semantic_count: number;
  /** False when no embedding provider answered, so the UI can say why the
   *  semantic half is missing instead of implying there was no match. */
  semantic_available: boolean;
}

export async function searchDocuments(
  query: string,
  opts: { limit?: number; runId?: string; signal?: AbortSignal } = {}
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (opts.limit) params.set("limit", String(opts.limit));
  if (opts.runId) params.set("run_id", opts.runId);

  const r = await fetch(`${ANALYZER_BASE}/search?${params}`, { signal: opts.signal });
  if (!r.ok) throw new Error(`Search failed: ${r.status}`);
  return r.json();
}

export interface DocumentChunk {
  chunk_id: string;
  html: string;
  content_hash: string;
}

export async function getDocumentChunks(
  documentId: string
): Promise<{ document: DocumentSummary; chunks: DocumentChunk[] }> {
  return fetchJson(`${INGESTOR_BASE}/documents/${documentId}`);
}