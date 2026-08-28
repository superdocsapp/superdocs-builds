export interface UploadUrlRequest {
  filename: string;
  content_type: string;
  size_bytes: number;
  purpose?: "document" | "attachment" | "export-html";
}

export interface UploadUrlResponse {
  upload_id: string;
  upload_url: string;
  expires_at: string;
  expires_in_seconds: number;
  max_size_bytes: number;
  curl_example: string;
}

export interface ProcessDocumentRequest {
  session_id: string;
  filename: string;
  parse_mode?: "document" | "attachment";
  return_html?: boolean;
}

export interface ProcessDocumentResponse {
  html?: string | null;
  session_id: string;
  filename: string;
  chunks_count?: number | null;
  version_id?: string | null;
  job_id?: string | null;
  status: string;
  parse_mode: string;
  page_setup?: Record<string, unknown> | null;
  warnings?: IngestWarning[] | null;
}

export interface IngestWarning {
  code: string;
  message: string;
  [key: string]: unknown;
}

export interface PageSetup {
  width_in?: number;
  height_in?: number;
  margin_in?: Record<string, number>;
  orientation?: string;
  [key: string]: unknown;
}

export interface AsyncChatRequest {
  message: string;
  session_id: string;
  document_html?: string | null;
  approval_mode?: "approve_all" | "ask_every_time";
  model_tier?: "core" | "turbo" | "pro" | "max";
  thinking_depth?: "fast" | "balanced" | "deep";
}

export interface AsyncChatResponse {
  job_id: string;
  session_id: string;
  status: string;
  message?: string;
}

export interface ProposedChange {
  change_id: string;
  operation: string;
  chunk_id: string;
  document_id?: string;
  old_html: string;
  new_html: string;
  ai_explanation?: string;
  insert_after_chunk_id?: string | null;
}

export interface ProposedChangeBatch {
  type: "batch_approval" | "single_approval";
  batch_id: string;
  batch_total: number;
  changes: ProposedChange[];
}

export interface IntermediateResponse {
  type: string;
  content: string;
  context?: string;
  sequence?: number;
  timestamp?: string;
}

export interface JobMetadata {
  filename?: string | null;
  file_size?: number | null;
  content_type?: string | null;
  message?: string | null;
  document_html_provided?: boolean;
  pending_changes?: ProposedChange[] | null;
  intermediate_responses?: IntermediateResponse[] | null;
  awaiting_kind?: string | null;
  request_message?: string;
  model_tier?: string;
  cumulative_tokens?: number;
  [key: string]: unknown;
}

export interface JobStatus {
  job_id: string;
  session_id: string;
  job_type: string;
  status: JobState;
  progress?: number;
  error?: string | null;
  result?: {
    response?: string;
    session_id?: string;
    document_changes?: { updated_html?: string };
  } | null;
  metadata?: JobMetadata | null;
}

export type JobState =
  | "pending"
  | "in_progress"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface ApprovalRequest {
  job_id: string;
  approved: boolean;
  change_id?: string | null;
  changes?: { change_id: string; approved?: boolean; feedback?: string }[];
  feedback?: string;
}

export interface ApprovalResponse {
  status: string;
  message?: string;
  batch_complete?: boolean;
}

export interface ExportOptions {
  paper_size?: "A4" | "Letter" | "A3" | "Legal";
  orientation?: "portrait" | "landscape";
  margins?: "narrow" | "normal" | "wide" | "custom";
  custom_margins_inches?: Record<string, number>;
  filename?: string;
  embed_images?: boolean;
  watermark_text?: string;
  watermark_opacity?: number;
  fidelity?: "strict" | "compat";
}

export interface ExportRequest {
  session_id?: string;
  html?: string | null;
  format: "docx" | "pdf" | "html" | "markdown" | "txt";
  options?: ExportOptions;
}

export interface ExportWarning {
  code: string;
  message: string;
  [key: string]: unknown;
}

export interface ExportResult {
  body: Buffer;
  contentType?: string;
  filename?: string;
  warnings: ExportWarning[];
}

export interface QuotaInfo {
  tier: string;
  monthly_limit: number;
  used: number;
  remaining: number;
  resets_at?: string;
}
