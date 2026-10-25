// ============================================================
// Types derived from backend Pydantic schemas
// ============================================================

export type RegisterStatus =
  | "NOT_RECEIVED"
  | "RECEIVED"
  | "UNDER_REVIEW"
  | "REVIEWED"
  | "OVERDUE";

export type TechnicalStatus =
  | "PENDING"
  | "PENDING_REVIEW"
  | "REVIEWED_DEVIATION"
  | "REVIEWED_COMPLIANT";

export type FindingStatus =
  | "PENDING_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "CLARIFICATION_REQUESTED";

export type TransmittalStatus =
  | "DRAFT"
  | "UPLOADED"
  | "PROCESSING_EDIT"
  | "AWAITING_APPROVAL"
  | "EDIT_APPROVED"
  | "EDIT_REJECTED"
  | "EXPORTED";

export type ReviewDecision =
  | "APPROVE"
  | "REJECT"
  | "REQUEST_CLARIFICATION";

// ============================================================
// Register / Submittal
// ============================================================

export interface RegisterItem {
  id: string;
  project_id: string;
  number: string;
  title: string;
  description: string | null;
  specification_section: string;
  required_by: string | null;
  required_form: string | null;
  source_evidence: string | null;
  specification_revision: string | null;
  status: TechnicalStatus;
  register_status: RegisterStatus;
  due_date: string | null; // ISO date string
  created_at: string;
  updated_at: string | null;
  finding_count: number;
  unresolved_finding_count: number;
  reviewed_finding_count: number;
}

export interface RegisterResponse {
  project_id: string;
  items: RegisterItem[];
}

export interface OverdueRegisterResponse {
  project_id: string;
  overdue_count: number;
  items: RegisterItem[];
}

// ============================================================
// Finding
// ============================================================

export interface Finding {
  id: string;
  attribute: string;
  requirement: string;
  submitted_value: string;
  result: "MATCH" | "DEVIATION";
  specification_evidence: string;
  submission_evidence: string;
  status: FindingStatus;
  reviewer: string | null;
  reviewer_comment: string | null;
  reviewed_at: string | null;
}

// ============================================================
// Submittal Detail
// ============================================================

export interface TransmittalSummary {
  id: string;
  number: string;
  status: TransmittalStatus;
  superdocs_session_id: string | null;
  superdocs_job_id: string | null;
  export_url: string | null;
  created_at: string | null;
}

export interface SubmittalDetail extends RegisterItem {
  findings: Finding[];
  transmittal: TransmittalSummary | null;
}

// ============================================================
// Review
// ============================================================

export interface ReviewFindingRequest {
  reviewer: string;
  decision: ReviewDecision;
  comment?: string | null;
}

export interface ReviewFindingResponse {
  finding_id: string;
  status: FindingStatus;
  reviewer: string;
  comment: string | null;
  reviewed_at: string;
}

// ============================================================
// Transmittal
// ============================================================

export interface CreateTransmittalResponse {
  transmittal_id: string;
  number: string;
  status: TransmittalStatus;
  session_id: string | null;
  job_id: string | null;
  export_url: string | null;
}

export interface EditTransmittalResponse {
  transmittal_id: string;
  status: TransmittalStatus;
  session_id: string;
  job_id: string;
}

export interface ProposedChange {
  change_id?: string;
  description?: string;
  original?: string;
  proposed?: string;
  reason?: string;
  [key: string]: unknown;
}

export interface TransmittalJobResponse {
  transmittal_id: string;
  job_id: string;
  status: string;
  proposed_changes: ProposedChange[];
  job: Record<string, unknown>;
}

export interface ApproveTransmittalResponse {
  transmittal_id: string;
  approved: boolean;
  status: TransmittalStatus;
  result: unknown;
}

export interface ExportTransmittalResponse {
  transmittal_id: string;
  status: TransmittalStatus;
  format: string;
  export: unknown;
}

// ============================================================
// Workflow Run
// ============================================================

export interface RunWorkflowResponse {
  thread_id: string;
  stage: string;
  review_status: string;
  submittal_id: string;
  findings_count: number;
}

// ============================================================
// Health
// ============================================================

export interface HealthResponse {
  status: string;
}
