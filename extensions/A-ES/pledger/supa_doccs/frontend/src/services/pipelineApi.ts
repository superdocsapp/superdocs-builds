/**
 * Pipeline API service — upload documents and start pipeline runs.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

export interface UploadResponse {
  document_id: string;
  document_version_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
}

export interface StartPipelineResponse {
  run_id: string;
  status: string;
}

export interface RunListItem {
  id: string;
  status: string;
  started_at: string;
  document_id: string | null;
  filename: string | null;
  pile_id: string | null;
  pile_name: string | null;
  needs_recheck_count?: number;
}

export interface NodeDetails {
  node_id: string;
  status: string;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  started_at: string | null;
  ended_at: string | null;
  // Node-specific fields
  extracted_text_preview?: string;
  text_length?: number;
  classification_label?: string;
  classification_confidence?: number;
  classification_scores?: Record<string, number>;
  chunk_count?: number;
  chunks_preview?: Array<{ index: number; length: number; text_preview: string }>;
  claim_count?: number;
  claims?: Array<{
    claim_id: string;
    claim_text: string;
    confidence: number;
    citation_status: string;
  }>;
  verdicts?: Array<{
    claim_id: string;
    verdict: string;
    confidence: number;
    needs_human_review: boolean;
    rule_id?: string;
  }>;
  findings?: Array<{
    claim_id?: string;
    rule_id?: string;
    verdict?: string;
    reason?: string;
    finding_type?: string;
    description?: string;
    severity?: string;
    source?: string;
  }>;
  finding_count?: number;
  queue_buckets?: {
    auto_approve: string[];
    escalate: string[];
    auto_reject: string[];
  };
  auto_approve_count?: number;
  escalate_count?: number;
  auto_reject_count?: number;
  decisions?: Array<{
    claim_id: string;
    decision_value: string;
    reviewer_id: string;
    justification: string;
  }>;
  decision_count?: number;
  mime_type?: string;
  file_size?: number;
  total_claims?: number;
  total_findings?: number;
  final_status?: string;
}

export interface RunCost {
  run_id: string;
  total_duration_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  stages: Array<{
    stage: string;
    step_order: number;
    status: string;
    duration_ms: number;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
  }>;
}

/**
 * Upload a document file to the backend.
 */
export async function uploadDocument(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${BASE_URL}/documents/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(error.detail || `Upload failed: ${response.status}`);
  }

  return response.json();
}

/**
 * Start a pipeline run on an uploaded document.
 */
export async function startPipeline(
  documentId: string,
  documentVersionId: string,
): Promise<StartPipelineResponse> {
  const response = await fetch(`${BASE_URL}/runs/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      document_id: documentId,
      document_version_id: documentVersionId,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Start failed' }));
    throw new Error(error.detail || `Start failed: ${response.status}`);
  }

  return response.json();
}

/**
 * Get the list of all pipeline runs.
 */
export async function fetchPipelineRuns(): Promise<RunListItem[]> {
  const response = await fetch(`${BASE_URL}/runs`);
  if (!response.ok) return [];
  return response.json();
}

/**
 * Get detailed node output for a specific node in a run.
 */
export async function fetchNodeDetails(runId: string, nodeId: string): Promise<NodeDetails> {
  const response = await fetch(`${BASE_URL}/runs/${runId}/node/${nodeId}/details`);
  if (!response.ok) {
    throw new Error(`Failed to fetch node details: ${response.status}`);
  }
  return response.json();
}

/**
 * Get cost breakdown for a pipeline run.
 */
export async function fetchRunCost(runId: string): Promise<RunCost> {
  const response = await fetch(`${BASE_URL}/runs/${runId}/cost`);
  if (!response.ok) {
    throw new Error(`Failed to fetch run cost: ${response.status}`);
  }
  return response.json();
}

export interface HistoryEntry {
  event_id: string;
  timestamp: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_id: string;
  source_document_id: string | null;
  previous_state: Record<string, unknown> | null;
  new_state: Record<string, unknown>;
}

export interface RunHistory {
  run_id: string;
  entries: HistoryEntry[];
  total: number;
}

export interface ResumeRunResponse {
  run_id: string;
  status: string;
  resumed_from: string | null;
  next_node: string | null;
}

// ─── Deliverable API ─────────────────────────────────────────────────────────

export interface DeliverableCitation {
  start_offset?: number;
  end_offset?: number;
  chunk_index?: number;
  page_number?: number;
  section_id?: string;
  clause_ref?: string;
  snippet?: string;
}

export interface DeliverableClaim {
  claim_id: string;
  claim_type: string;
  extracted_text: string;
  confidence: number;
  source_document_id: string;
  /** "grounded" | "unverifiable" — unverifiable ⇒ no source span (Prompt 3.6) */
  citation_status: string;
  /** Absent when the extraction stage recorded no source span */
  citation?: DeliverableCitation | null;
}

export interface DeliverableSection {
  key: string;
  content_hash: string;
  claims: DeliverableClaim[];
}

export interface RunDeliverable {
  run_id: string;
  deliverable_hash: string;
  section_count: number;
  claim_count: number;
  sections: Record<string, DeliverableSection>;
  created_at: string;
}

/**
 * Fetch the persisted deliverable for a run (assembled by finalize,
 * updated by Movement 3 incremental updates).
 */
export async function fetchRunDeliverable(runId: string): Promise<RunDeliverable> {
  const response = await fetch(`${BASE_URL}/runs/${runId}/deliverable`);
  if (!response.ok) {
    throw new Error(`Failed to fetch deliverable: ${response.status}`);
  }
  return response.json();
}

// ─── Findings audit-trail API ────────────────────────────────────────────────

export interface FindingCitation {
  claim_id?: string | null;
  snippet?: string | null;
  page_number?: number | null;
  section_id?: string | null;
  start_offset?: number | null;
  end_offset?: number | null;
  clause_ref?: string | null;
  source_document_id?: string | null;
}

export interface FindingAuditEvent {
  event_id: string;
  timestamp: string;
  action: string;
  actor_id: string;
  details: Record<string, unknown>;
}

/** status: pending | approved | rejected | unqueued */
export interface FindingRecord {
  finding_key: string;
  claim_id?: string | null;
  rule_id?: string | null;
  description: string;
  severity?: string | null;
  evaluation_method?: string | null;
  source_node?: string | null;
  playbook_id?: string | null;
  citations: FindingCitation[];
  status: string;
  decided_by?: string | null;
  decided_at?: string | null;
  justification?: string | null;
  queued_at?: string | null;
  first_generated_at?: string | null;
  events: FindingAuditEvent[];
}

export interface RunFindings {
  run_id: string;
  total: number;
  pending: number;
  resolved: number;
  items: FindingRecord[];
}

/**
 * Every finding ever generated for a run with its full audit trail
 * (read directly from audit_events, joined with current queue status).
 */
export async function fetchRunFindings(runId: string): Promise<RunFindings> {
  const response = await fetch(`${BASE_URL}/runs/${runId}/findings`);
  if (!response.ok) {
    throw new Error(`Failed to fetch findings: ${response.status}`);
  }
  return response.json();
}

/**
 * Get the full change history (audit trail) for a pipeline run.
 */
export async function fetchRunHistory(runId: string): Promise<RunHistory> {
  const response = await fetch(`${BASE_URL}/runs/${runId}/history`);
  if (!response.ok) {
    throw new Error(`Failed to fetch run history: ${response.status}`);
  }
  return response.json();
}

/**
 * Resume a paused/interrupted/cancelled pipeline run from its last checkpoint.
 */
export async function resumeRun(runId: string): Promise<ResumeRunResponse> {
  const response = await fetch(`${BASE_URL}/runs/${runId}/resume`, {
    method: 'POST',
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Resume failed' }));
    throw new Error(error.detail || `Resume failed: ${response.status}`);
  }
  return response.json();
}

// ─── Piles API ───────────────────────────────────────────────────────────────

export interface PileListItem {
  id: string;
  name: string;
  status: string;
  created_at: string;
  document_count: number;
}

export interface PileDocumentItem {
  document_id: string;
  filename: string;
  mime_type: string;
  added_at: string;
}

// ─── Document fact view ──────────────────────────────────────────────────────

export interface FactCitation {
  start_offset: number;
  end_offset: number;
  snippet: string;
  page_number: number | null;
  section_id: string | null;
}

export interface DocumentFact {
  field_name: string;
  extracted_value: string | null; // null ⇒ "not found"
  confidence: number | null;
  extraction_method: string | null; // structured | llm | llm_fallback | regex_fallback
  citation_status: 'grounded' | 'unverifiable' | 'not_found';
  cited_span: FactCitation | null;
}

export interface DocumentFactsResponse {
  document_id: string;
  document_version_id: string;
  filename: string;
  classification: string | null;
  run_id: string | null;
  source_text: string;
  facts: DocumentFact[];
}

/**
 * Fetch every fact extracted from a document, with server-resolved
 * citation snippets and the full source text for inline highlighting.
 */
export async function fetchDocumentFacts(
  documentId: string,
  runId?: string,
): Promise<DocumentFactsResponse> {
  const params = new URLSearchParams();
  if (runId) params.set('run_id', runId);
  const qs = params.toString();
  const response = await fetch(
    `${BASE_URL}/documents/${documentId}/facts${qs ? `?${qs}` : ''}`,
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch document facts: ${response.status}`);
  }
  return response.json();
}

export interface PileDetail {
  id: string;
  name: string;
  status: string;
  created_at: string;
  documents: PileDocumentItem[];
}

export interface UploadToPileResponse {
  pile_id: string;
  uploaded: Array<{
    document_id: string;
    filename: string;
    mime_type: string;
    size_bytes: number;
  }>;
  errors: string[];
}

/**
 * List all active piles.
 */
export async function fetchPiles(): Promise<PileListItem[]> {
  const response = await fetch(`${BASE_URL}/piles`);
  if (!response.ok) return [];
  return response.json();
}

export interface SeedDemoResponse {
  status: 'seeded' | 'skipped';
  reason?: string;
  pile_id?: string;
  run_id?: string;
  document_count?: number;
  conflicts?: Array<{
    field_name: string;
    expected_value: string;
    contradicting_value: string;
    repayment_filename: string;
  }>;
}

/**
 * Seed the fixed demo pile (runs the same logic as scripts/seed_demo.py,
 * in-process on the backend). Idempotent — returns status "skipped" if the
 * demo pile already exists.
 */
export async function seedDemo(): Promise<SeedDemoResponse> {
  const response = await fetch(`${BASE_URL}/demo/seed`, { method: 'POST' });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to seed demo' }));
    throw new Error(error.detail || `Seed demo failed: ${response.status}`);
  }
  return response.json();
}

/**
 * Create a new pile.
 */
export async function createPile(name: string): Promise<{ id: string; name: string }> {
  const response = await fetch(`${BASE_URL}/piles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to create pile' }));
    throw new Error(error.detail || `Create pile failed: ${response.status}`);
  }
  return response.json();
}

/**
 * Get pile details including its documents.
 */
export async function fetchPileDetail(pileId: string): Promise<PileDetail> {
  const response = await fetch(`${BASE_URL}/piles/${pileId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch pile: ${response.status}`);
  }
  return response.json();
}

/**
 * Upload one or more files into a pile.
 */
export async function uploadToPile(pileId: string, files: File[]): Promise<UploadToPileResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }

  const response = await fetch(`${BASE_URL}/piles/${pileId}/documents`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(error.detail || `Upload to pile failed: ${response.status}`);
  }

  return response.json();
}

/**
 * Start a pipeline run against a pile.
 * Only pile_id is required — the backend resolves all pile documents
 * and picks the latest version for each.
 */
export async function startPipelineWithPile(
  pileId: string,
): Promise<StartPipelineResponse> {
  const response = await fetch(`${BASE_URL}/runs/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pile_id: pileId,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Start failed' }));
    throw new Error(error.detail || `Start failed: ${response.status}`);
  }

  return response.json();
}


// ─── Incremental Update API ──────────────────────────────────────────────────

export interface IncrementalUpdateResponse {
  pile_id: string;
  document_id: string;
  run_id: string;
  affected_sections: string[];
  unaffected_sections: string[];
  conflicts_detected: number;
  sections_updated: number;
  approval_items_created: string[];
  section_hashes: Record<string, string>;
}

/**
 * Upload a document via the incremental update path.
 *
 * Unlike a full pipeline run, this only extracts claims from the new document,
 * identifies affected sections, and routes conflicts to the approval queue.
 * Unaffected sections remain byte-identical.
 */
export async function uploadIncrementalDocument(
  pileId: string,
  files: File[],
): Promise<IncrementalUpdateResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }

  const response = await fetch(`${BASE_URL}/piles/${pileId}/incremental`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Incremental update failed' }));
    throw new Error(error.detail || `Incremental update failed: ${response.status}`);
  }

  return response.json();
}


// ─── Delete API ──────────────────────────────────────────────────────────────

/**
 * Delete a pile (soft delete — marks as deleted).
 */
export async function deletePile(pileId: string): Promise<void> {
  const response = await fetch(`${BASE_URL}/piles/${pileId}`, { method: 'DELETE' });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Delete failed' }));
    throw new Error(error.detail || `Delete pile failed: ${response.status}`);
  }
}

/**
 * Delete a pipeline run and its steps.
 */
export async function deleteRun(runId: string): Promise<void> {
  const response = await fetch(`${BASE_URL}/runs/${runId}`, { method: 'DELETE' });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Delete failed' }));
    throw new Error(error.detail || `Delete run failed: ${response.status}`);
  }
}
