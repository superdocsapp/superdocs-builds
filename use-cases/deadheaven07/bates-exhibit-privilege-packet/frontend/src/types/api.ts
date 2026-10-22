export interface Packet {
  id: string;
  name: string;
  description: string | null;
  bates_prefix: string;
  bates_start_number: number;
  bates_padding: number;
  created_at: string;
  updated_at: string;
  document_count?: number;
  total_pages?: number;
  status?: string;
}

export interface CreatePacketRequest {
  name: string;
  description?: string;
  bates_prefix?: string;
  bates_start_number?: number;
  bates_padding?: number;
}

export interface Document {
  id: string;
  packet_id: string;
  display_order: number;
  original_filename: string;
  mime_type: string;
  file_size: number;
  sha256: string;
  document_type: DocumentType;
  page_count: number;
  processing_status: ProcessingStatus;
  processing_error: string | null;
  retry_count: number;
  last_completed_step: string | null;
  original_sha256: string;
  processed_sha256: string | null;
  final_sha256: string | null;
  superdocs_session_id: string | null;
  superdocs_document_id: string | null;
  description: string | null;
  description_source: string | null;
  description_generated_at: string | null;
  is_searchable: boolean;
  uploaded_at: string;
  processed_at: string | null;
  completed_at: string | null;
  bates_range?: string;
  privilege_status?: string;
}

export type DocumentType = 'pdf' | 'docx' | 'scanned_pdf' | 'image' | 'unknown';

export type ProcessingStatus = 
  | 'queued' 
  | 'processing' 
  | 'ocr' 
  | 'ai_analysis' 
  | 'waiting_review' 
  | 'approved' 
  | 'bates_assigned' 
  | 'assembling' 
  | 'completed' 
  | 'failed';

export interface UploadDocumentResponse {
  id: string;
  filename: string;
  document_type: DocumentType;
  page_count: number;
  status: ProcessingStatus;
  is_searchable: boolean;
}

export interface DocumentListResponse {
  id: string;
  filename: string;
  document_type: DocumentType;
  page_count: number;
  status: ProcessingStatus;
  display_order: number;
  bates_range: string | null;
  privilege_status: string;
  is_searchable: boolean;
  uploaded_at: string;
}

export interface ProcessingStatusResponse {
  packet_id: string;
  total_documents: number;
  status_breakdown: Record<string, number>;
  documents: ProcessingDocumentStatus[];
}

export interface ProcessingDocumentStatus {
  id: string;
  filename: string;
  status: ProcessingStatus;
  page_count: number;
  is_searchable: boolean;
  error: string | null;
  retry_count: number;
}

export interface BatesPreviewResponse {
  packet_id: string;
  prefix: string;
  start_label: string | null;
  end_label: string | null;
  documents: Array<{
    document_id: string;
    document_name: string;
    page_count: number;
    status: string;
    bates_start: string | null;
    bates_end: string | null;
    skipped: boolean;
  }>;
}

export interface DocumentDetailResponse {
  id: string;
  filename: string;
  document_type: DocumentType;
  page_count: number;
  status: ProcessingStatus;
  display_order: number;
  mime_type: string;
  file_size: number;
  sha256: string;
  is_searchable: boolean;
  description: string | null;
  pages: Page[];
  bates_assignments: BatesAssignment[];
  privilege_decision: PrivilegeDecision | null;
}

export interface Page {
  page_number: number;
  has_text: boolean;
  width: number | null;
  height: number | null;
}

export interface BatesAssignment {
  page_number: number;
  bates_number: number;
  bates_label: string;
}

export interface PrivilegeDecision {
  id: string;
  document_id: string;
  status: PrivilegeStatus;
  category: PrivilegeCategory | null;
  reason: string | null;
  bates_start: string | null;
  bates_end: string | null;
  reviewer: string;
  decided_at: string | null;
}

export type PrivilegeStatus = 'pending' | 'privileged' | 'not_privileged';
export type PrivilegeCategory = 'attorney_client' | 'work_product' | 'other';

export interface PrivilegeDecisionRequest {
  status: PrivilegeStatus;
  category?: PrivilegeCategory;
  reason?: string;
  reviewer: string;
}

export interface PrivilegeLogResponse {
  packet_id: string;
  packet_name: string;
  generated_at: string;
  total_privileged_documents: number;
  entries: PrivilegeLogEntry[];
}

export interface PrivilegeLogEntry {
  document_id: string;
  filename: string;
  bates_range: string;
  privilege_category: string;
  reason: string;
  reviewer: string;
  decided_at: string | null;
  page_count: number;
}

export interface RedactionCandidate {
  id: string;
  document_id: string;
  document_name: string;
  page_number: number;
  category: RedactionCategory;
  matched_text: string;
  context_before: string | null;
  context_after: string | null;
  coordinates: {
    x0: number;
    y0: number;
    x1: number;
    y1: number;
  };
  status: RedactionStatus;
  reason: string | null;
  proposed_at: string;
  proposed_by: string;
  approval: RedactionApproval | null;
}

export type RedactionCategory = 
  | 'name' 
  | 'account_number' 
  | 'medical_term' 
  | 'ssn' 
  | 'email' 
  | 'phone' 
  | 'address' 
  | 'other';

export type RedactionStatus = 
  | 'proposed' 
  | 'pending_approval' 
  | 'approved' 
  | 'rejected' 
  | 'applied' 
  | 'verified' 
  | 'failed';

export interface RedactionApproval {
  status: RedactionStatus;
  approver: string;
  approved_at: string | null;
  verified_at?: string | null;
}

export interface RedactionApprovalRequest {
  status: 'approved' | 'rejected';
  approver: string;
}

export interface ApplyRedactionsRequest {
  document_ids: string[];
}

export interface AIAnalysisRequest {
  instruction: string;
  approval_mode: string;
  model_tier: string;
}

export interface AIAnalysisResponse {
  message: string;
  job_id: string;
  document_id: string;
}

export interface AnalysisStatusResponse {
  status: string;
  job_id: string;
  awaiting_kind?: string;
  continue_prompt?: any;
  changes?: ProposedChange[];
  result?: any;
  error?: string;
}

export interface ProposedChange {
  change_id: string;
  operation: string;
  chunk_id: string | null;
  old_html: string | null;
  new_html: string | null;
  ai_explanation: string;
  insert_after_chunk_id: string | null;
  document_id: string | null;
}

export interface ApproveChangesRequest {
  job_id: string;
  approved: boolean;
  changes: any[];
  feedback?: string;
}

export interface ContinueJobRequest {
  job_id: string;
  continue_job: boolean;
}

export interface BuildPacketResponse {
  message: string;
  final_packet: string;
  exhibits_dir: string;
  exhibit_index: string;
  privilege_log: string;
  manifest: string;
  total_pages: number;
  total_documents: number;
}

export interface ValidationResponse {
  valid: boolean;
  errors: string[];
  warnings: string[];
  total_documents: number;
  total_pages: number;
  bates_range: string | null;
}

export interface ManifestResponse {
  id: string;
  packet_id: string;
  total_pages: number;
  total_documents: number;
  bates_start: string | null;
  bates_end: string | null;
  generated_at: string;
  validation_passed: boolean | null;
  validation_details: any | null;
  final_packet_sha256: string | null;
  final_packet_path: string | null;
  entries: ManifestEntry[];
}

export interface ManifestEntry {
  id: string;
  document_id: string;
  exhibit_identifier: string;
  bates_start: string;
  bates_end: string;
  page_count: number;
  original_sha256: string;
  processed_sha256: string | null;
  final_sha256: string | null;
  description: string | null;
  privilege_status: string | null;
  privilege_category: string | null;
  privilege_reason: string | null;
  applied_redactions: any[];
  final_file_path: string | null;
}

export interface Exhibit {
  exhibit_identifier: string;
  bates_range: string;
  page_count: number;
  description: string;
  file_exists: boolean;
  file_path: string;
  sha256: string;
}

export interface SearchSnippet {
  page_number: number;
  snippet: string;
}

export interface SearchResult {
  document_id: string;
  document_name: string;
  document_type: DocumentType;
  page_count: number;
  status: string;
  matched_fields: string[];
  snippets: SearchSnippet[];
}

export interface SearchResponse {
  packet_id: string;
  query: string;
  total_results: number;
  results: SearchResult[];
}

export interface BatesSearchResponse {
  bates_label: string;
  bates_number: number;
  page_number: number;
  document_id: string;
  document_name: string;
  packet_id: string;
}

export interface AuditEvent {
  id: string;
  packet_id: string | null;
  document_id: string | null;
  document_name: string | null;
  event_type: string;
  user_id: string | null;
  metadata: any;
  timestamp: string;
}

export interface AuditTrailResponse {
  packet_id: string;
  document_id?: string;
  document_name?: string;
  total_events: number;
  events: AuditEvent[];
}