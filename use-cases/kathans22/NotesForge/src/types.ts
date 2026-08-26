// Shapes below are taken from the live OpenAPI schema at
// https://api.superdocs.app/openapi.json (components.schemas.*), not guessed.

/** `usage` block attached to chat/job responses. All fields are nullable
 * server-side (e.g. absent for unauthenticated calls). */
export interface UsageBlock {
  monthly_used: number | null;
  monthly_limit: number | null;
  monthly_remaining: number | null;
  was_billable: boolean | null;
  ops_charged: number | null;
  quota_exhausted: boolean | null;
  subscription_tier: string | null;
}

export interface AgentQuota {
  tier: string;
  monthly_limit: number;
  used: number;
  remaining: number;
  resets_at: string | null;
}

/** Response from POST /v1/agents/signup and the shape persisted verbatim
 * to CONFIG.CRED_PATH. */
export interface AgentCredentials {
  account_id: string;
  slug: string;
  email: string;
  api_key: string;
  quota: AgentQuota;
  endpoints: Record<string, string>;
  mcp_setup: Record<string, string>;
  handoff: Record<string, string>;
  important: string;
}

/** Response from GET /v1/agents/whoami. Note this does NOT include slug,
 * email, endpoints, mcp_setup, handoff, or important — those only ever
 * come from the original POST /v1/agents/signup response. */
export interface AgentWhoamiResponse {
  account_id: string;
  tier: string;
  quota: AgentQuota;
  is_agent_account: boolean;
  adopted: boolean | null;
}

/** A single proposed/applied section-level edit. */
export interface PendingChange {
  change_id: string;
  operation: string;
  chunk_id: string | null;
  document_id: string | null;
  old_html: string | null;
  new_html: string | null;
  ai_explanation: string | null;
}

/** `document_changes` on a chat response. `updated_html` is null in
 * response_mode='compact' — use `chunk_diffs` to verify edits for free. */
export interface DocumentChanges {
  updated_html: string | null;
  version_id: string | null;
  changes_summary: string | null;
  requires_approval: boolean | null;
  pending_changes: PendingChange[] | null;
  chunk_diffs: PendingChange[] | null;
}

/** Request body for POST /v1/chat and POST /v1/chat/async. `response_mode:
 * 'compact'` suppresses full document HTML in favour of per-section
 * chunk_diffs — the token-cheap way to edit large documents. */
export interface ChatRequest {
  message: string;
  session_id: string;
  document_html?: string | null;
  model_tier?: "core" | "turbo" | "pro" | "max" | null;
  thinking_depth?: "fast" | "balanced" | "deep" | null;
  approval_mode?: "approve_all" | "ask_every_time" | null;
  response_mode?: "full" | "compact" | null;
  document_id?: string | null;
}

/** Response from POST /v1/chat. */
export interface ChatResponse {
  response: string;
  session_id: string;
  document_changes: DocumentChanges | null;
  usage: UsageBlock | null;
}

/** Response from POST /v1/chat/async — a job to poll, not a result. */
export interface AsyncChatResponse {
  job_id: string;
  session_id: string;
  status: string;
  message: string;
}

/** Response from POST /v1/chat/{session_id}/continue. The OpenAPI schema
 * leaves this untyped ({}); this is the minimal shape the docs' description
 * implies. The authoritative state is always the next getJob() poll. */
export interface ContinueResponse {
  job_id: string;
  status: string;
}

/** Job metadata. `awaiting_kind` is documented (agent-editing-playbook guide)
 * but not modeled in the strict OpenAPI schema — 'continue_prompt' marks a
 * large-edit continue pause, distinct from a pending_changes approval pause. */
export interface JobMetadata {
  awaiting_kind?: string | null;
  pending_changes?: PendingChange[] | null;
  intermediate_responses?: Record<string, unknown>[] | null;
}

/** Payload inside JobStatus.result once status is 'completed'. */
export interface JobResult {
  response: string | null;
  session_id: string | null;
  document_changes: DocumentChanges | null;
  usage: UsageBlock | null;
  attachment_id: string | null;
}

/** Response from GET /v1/jobs/{job_id}. */
export interface JobStatus {
  job_id: string;
  session_id: string;
  job_type: string;
  status:
    | "pending"
    | "in_progress"
    | "awaiting_approval"
    | "completed"
    | "failed"
    | "cancelled";
  progress: number;
  result: JobResult | null;
  error: string | null;
  metadata: JobMetadata | null;
}

/** Entry in GET /v1/sessions/{session_id}/documents. `document_id` is the
 * session-local slot id; `durable_document_id` is the permanent id (null
 * until first save). Confirmed live — the strict OpenAPI schema leaves this
 * endpoint untyped ({}). */
export interface SessionDocumentEntry {
  document_id: string;
  durable_document_id: string | null;
  title: string | null;
  chunks_count: number;
  focused: boolean;
  html: string | null;
}

/** Response from GET /v1/sessions/{session_id}/documents. */
export interface SessionDocumentsResponse {
  session_id: string;
  focused_document_id: string | null;
  documents: SessionDocumentEntry[];
  file_cap_reached: boolean;
}

/** Request body for POST /v1/agents/handoff. */
export interface AgentHandoffRequest {
  email: string;
  working_context?: string | null;
  code_location?: string | null;
}

/** Response from POST /v1/agents/handoff. */
export interface HandoffResponse {
  takeover_code: string;
}

export interface ExportOptions {
  paper_size?: "A4" | "Letter" | "A3" | "Legal";
  orientation?: "portrait" | "landscape";
  margins?: "narrow" | "normal" | "wide" | "custom";
  filename?: string | null;
  embed_images?: boolean;
  watermark_text?: string | null;
}

/** Request body for POST /v1/downloads. */
export interface DownloadUrlRequest {
  session_id: string;
  format: "docx" | "pdf" | "html" | "markdown" | "txt" | "doc";
  filename?: string | null;
  options?: ExportOptions;
}

/** Response from POST /v1/downloads — a short-lived pre-signed GET URL. */
export interface DownloadUrlResponse {
  download_url: string;
  expires_at: string;
  expires_in_seconds: number;
  curl_example: string;
  filename: string;
  format: string;
}

/** Request body for POST /v1/uploads. */
export interface UploadUrlRequest {
  filename: string;
  content_type: string;
  size_bytes: number;
  purpose?: "document" | "attachment" | "export-html";
}

/** Response from POST /v1/uploads — a short-lived pre-signed PUT URL. */
export interface UploadUrlResponse {
  upload_id: string;
  upload_url: string;
  expires_at: string;
  expires_in_seconds: number;
  max_size_bytes: number;
  curl_example: string;
}

/** Request body for POST /v1/uploads/{upload_id}/process. */
export interface ProcessUploadRequest {
  session_id: string;
  filename: string;
  parse_mode?: "document" | "attachment";
  return_html?: boolean;
}

/** Response from POST /v1/uploads/{upload_id}/process. */
export interface ProcessDocumentResponse {
  html: string | null;
  session_id: string;
  filename: string;
  chunks_count: number | null;
  version_id: string | null;
  job_id: string | null;
  status: string;
  parse_mode: string;
}

/** One heading in a document's free `structure` block. */
export interface DocumentHeading {
  level: number;
  text: string;
  position: number;
}

/** The free, non-billable `structure` block from GET /v1/documents/{id}.
 * Use this to verify edits landed — never spend an export to check. */
export interface DocumentStructure {
  headings: DocumentHeading[];
  section_count: number;
  block_count: number;
  media: {
    images: number;
    diagrams: number;
  };
}

/** Response from GET /v1/documents/{document_id}. `html`/`page_setup`/
 * `version_id` are only populated when include_html=true; `structure` is
 * always present and always free (derived on read, never billed). */
export interface DocumentDetail {
  structure: DocumentStructure;
  html: string | null;
  page_setup: Record<string, unknown> | null;
  version_id: string | null;
}
