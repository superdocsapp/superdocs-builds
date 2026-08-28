// Mirrors backend QueueItemResponse
export interface QueueItem {
  id: string;
  run_id: string;
  item_type: ItemType;
  payload: QueueItemPayload;
  status: ItemStatus;
  queued_at: string; // ISO 8601
  decided_at: string | null;
  decision: "approved" | "rejected" | null;
  reviewer_id: string | null;
  justification: string | null;
}

export interface QueueItemPayload {
  summary: string;
  details: Record<string, unknown>;
  source_citations: SourceCitation[];
}

export interface SourceCitation {
  claim_id: string;
  claim_text: string;
  citation_status: "grounded" | "unverifiable";
  source_location: SourceLocation | null;
  /** Document the span points into — a citation without this is not
   *  auditable (spans are meaningless across re-uploads/pile documents). */
  document_id?: string | null;
  document_version_id?: string | null;
  snippet?: string;
  snippet_context_before?: string;
  snippet_context_after?: string;
}

export interface SourceLocation {
  page_number: number | null;
  section_id: string | null;
  start_offset: number;
  end_offset: number;
  clause_ref: string | null;
}

// API responses
export interface QueueListResponse {
  run_id: string;
  items: QueueItem[];
  total: number;
  pending: number;
}

export interface DecisionResponse {
  item_id: string;
  decision: "approved" | "rejected";
  success: boolean;
  error: string | null;
}

// Pipeline progress (from run history or progress endpoint)
export interface PipelineProgress {
  current_node: string | null;
  completed_nodes: string[];
  node_status: "completed" | "skipped" | "error" | null;
  run_status: "running" | "completed" | "failed" | "paused";
}

// Run summary for selector
export interface RunSummary {
  id: string;
  status: "running" | "completed" | "failed" | "paused";
  started_at: string;
  ended_at: string | null;
}

// Utility types
export type ItemType = "finding" | "conflict" | "proposed_update";
export type ItemStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "approved_needs_recheck";
export type SortField = "item_type" | "queued_at";

export interface QueueFilters {
  itemType: ItemType | null;
  unverifiableOnly: boolean;
}
