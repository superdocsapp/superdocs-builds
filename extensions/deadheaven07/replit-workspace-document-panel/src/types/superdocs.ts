export interface DocumentUploadResult {
  session_id: string;
  document_id: string;
  chunks_count: number;
  version_id: string;
  page_setup: Record<string, unknown>;
  html?: string;
  focused_document_id?: string;
}

export interface JobStatus {
  job_id: string;
  status: string;
  result?: Record<string, unknown>;
  error?: string;
  metadata?: Record<string, unknown>;
}

export interface ProposedChange {
  change_id: string;
  operation: string;
  chunk_id?: string;
  old_html?: string;
  new_html?: string;
  ai_explanation: string;
  insert_after_chunk_id?: string;
  document_id?: string;
}

export interface ProposedChangeBatch {
  batch_id: string;
  batch_total: number;
  changes: ProposedChange[];
  awaiting_kind: string;
  continue_prompt?: Record<string, unknown>;
}

export interface ExportResult {
  download_url: string;
  filename: string;
  format: string;
}

export interface ChatAsyncRequest {
  message: string;
  session_id: string;
  document_html?: string;
  approval_mode?: string;
  model_tier?: string;
}

export interface ApproveChangesRequest {
  job_id: string;
  approved: boolean;
  changes: ProposedChange[];
  feedback?: string;
  session_id: string;
}

export interface ContinueJobRequest {
  job_id: string;
  continue: boolean;
}

export interface ExportDocumentRequest {
  session_id: string;
  format: 'pdf' | 'docx';
  options?: Record<string, unknown>;
}

export interface SuperDocsConfig {
  baseUrl: string;
  apiKey: string;
}

export interface SessionInitRequest {
  session_id?: string;
}

// --- v2 platform capability types ---

export interface SyncHtmlRequest {
  session_id: string;
  document_id: string;
  html: string;
}

export interface SyncHtmlResponse {
  success: boolean;
  document_id: string;
  version_id: string;
}

export interface DocumentVersion {
  version_id: string;
  document_id: string;
  created_at: string;
  created_by: string;
  html: string;
  change_summary: string;
  is_current: boolean;
}

export interface GetVersionsResponse {
  versions: DocumentVersion[];
}

export interface TemplateVariable {
  name: string;
  description: string;
  default_value?: string;
  required: boolean;
}

export interface Template {
  id: string;
  name: string;
  description: string;
  document_type: 'readme' | 'spec' | 'user-guide';
  variables: TemplateVariable[];
  default_content: string;
}

export interface GetTemplatesResponse {
  templates: Template[];
}

export interface PromptVariable {
  name: string;
  description: string;
  default_value?: string;
  required: boolean;
}

export interface Prompt {
  id: string;
  name: string;
  description: string;
  template: string;
  variables: PromptVariable[];
}

export interface GetPromptsResponse {
  prompts: Prompt[];
}