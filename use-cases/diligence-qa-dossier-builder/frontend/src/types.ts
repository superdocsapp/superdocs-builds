export interface Evidence {
  evidence_id: string;
  document_id: string;
  filename: string;
  chunk_id: string;
  content: string;
  page_number?: number;
  section?: string;
  retrieval_score: number;
  evidence_type: 'supporting' | 'contradicting' | 'contextual' | 'insufficient';
}

export interface Citation {
  document_id: string;
  chunk_id: string;
  filename: string;
  page_number?: number;
  section?: string;
  excerpt?: string;
}

export type FindingStatus = 'pending' | 'running' | 'answered' | 'insufficient_evidence' | 'conflict' | 'failed';
export type ReviewStatus = 'not_required' | 'pending' | 'approved' | 'rejected' | 'edited';

export interface DossierFinding {
  id: string;
  dossier_id: string;
  question: string;
  status: FindingStatus;
  review_status: ReviewStatus;
  answer?: string;
  confidence?: number;
  reasoning_summary?: string;
  citations?: Citation[];
  supporting_evidence?: Evidence[];
  contradicting_evidence?: Evidence[];
  workflow_thread_id: string;
  review_reason?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}

export type DossierStatus = 'pending' | 'running' | 'completed' | 'failed' | 'review_required';

export interface Dossier {
  id: string;
  name: string;
  status: DossierStatus;
  created_at: string;
  updated_at: string;
  findings: DossierFinding[];
}

export interface Document {
  id: string;
  filename: string;
  file_size: number;
  file_type: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  error_message?: string;
  created_at: string;
}

export interface AccessibilityIssue {
  id: string;
  issue_type: string;
  location: string;
  details: string;
  original_content: string;
  can_auto_fix: boolean;
}

export interface AccessibilityAudit {
  original_text: string;
  issues: AccessibilityIssue[];
  detected_images: { url: string; current_alt: string }[];
}

export interface AccessibilityRemediationResponse {
  remediated_html: string;
  plain_language_report: string;
}

export interface StageMetric {
  stage_name: string;
  status: string;
  duration_ms: number;
  input_tokens?: number;
  output_tokens?: number;
  model_name?: string;
  provider_name?: string;
  estimated_cost?: number;
  error_message?: string;
  start_time: string;
  end_time: string;
}

export interface DossierMetrics {
  dossier_id: string;
  total_duration_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  estimated_total_cost: number;
  successful_stages: number;
  failed_stages: number;
  models_used: string[];
  providers_used: string[];
  stages: StageMetric[];
}
