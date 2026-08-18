export type StrengthBand = "strong" | "solid" | "mixed" | "reluctant";

export type Purpose =
  | "graduate_school"
  | "job"
  | "fellowship_or_award"
  | "other";

export interface EvidenceItem {
  claim: string;
  evidence: string;
}

export interface Intake {
  writerName: string;
  writerEmail: string;
  writerRole: string;
  subjectName: string;
  subjectRole: string;
  relationship: string;
  relationshipDurationMonths: number;
  purpose: Purpose;
  purposeOther?: string;
  strengthBand: StrengthBand;
  evidence: EvidenceItem[];
  reservations: string;
  toneNotes?: string;
  lengthPreference: "brief" | "standard" | "detailed";
  templateId?: string;
}

export interface PendingChange {
  change_id: string;
  operation: "edit" | "insert" | "delete";
  chunk_id: string;
  document_id: string;
  old_html: string;
  new_html: string;
  ai_explanation: string;
  insert_after_chunk_id?: string | null;
}

export type AwaitingKind = "continue_prompt" | "hitl_review";

export interface JobMetadata {
  awaiting_kind?: "continue_prompt";
  pending_changes?: PendingChange[];
  message?: string;
}

export interface JobStatusResponse {
  job_id: string;
  session_id: string;
  status:
    | "pending"
    | "in_progress"
    | "awaiting_approval"
    | "completed"
    | "failed"
    | "cancelled";
  progress?: number;
  result?: {
    response: string;
    document_changes?: {
      updated_html: string;
      changes_summary?: string;
    };
  } | null;
  error?: string | null;
  metadata?: JobMetadata;
}

export interface ChatAsyncResponse {
  job_id: string;
  session_id: string;
  status: string;
}

export interface UploadResponse {
  html: string;
  session_id: string;
  filename: string;
  chunks_count: number;
  version_id: string;
}

export interface SuperDocsTemplate {
  template_id: string;
  name: string;
  created_at?: string;
}

export interface ApproveDecision {
  change_id: string;
  approved: boolean;
  feedback?: string;
}
