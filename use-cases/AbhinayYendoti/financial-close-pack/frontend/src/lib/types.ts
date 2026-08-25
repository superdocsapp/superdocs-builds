export type CloseStatus = "COLLECTING" | "GENERATING" | "REVIEW_REQUIRED" | "READY_TO_CLOSE" | "CLOSED";

export type DocumentItem = {
  id: string;
  filename: string;
  content_type: string;
  document_type: string | null;
  suggested_type: string | null;
  status: "READY" | "PROCESSING";
  size: number;
  sha256: string;
  storage_key: string;
  uploaded_by: string;
  uploaded_at: string | null;
};

export type ChecklistItem = {
  id: string;
  title: string;
  document_type: string;
  owner: string;
  status: "COMPLETE" | "PENDING";
  evidence: string;
  completed_by: string | null;
  completed_at: string | null;
};

export type ReviewItem = {
  id: string;
  external_change_id: string | null;
  section: string;
  before_value: string;
  after_value: string;
  source_reference: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  reviewed_by: string | null;
  reviewed_at: string | null;
  reason: string | null;
  /** The redacted SuperDocs `approve_changes` receipt. Null until SuperDocs accepts it. */
  superdocs_approval: SuperDocsApproval | null;
  /** Set when a SuperDocs approval failed; the item stays PENDING. */
  error: string | null;
};

export type SuperDocsApproval = {
  document_id: string;
  approved_change_ids: string[];
  status?: string;
  request_id?: string;
  mode?: string;
};

export type SuperDocsOperation = {
  id: string;
  operation: "upload_document" | "send_edit_instruction" | "approve_changes" | "export_document";
  mode: string;
  status: "SUCCEEDED" | "FAILED";
  document_id: string | null;
  change_ids: string[];
  request_id: string | null;
  detail: string;
  error: string | null;
  started_at: string;
  completed_at: string;
  duration_ms: number;
};

export type SuperDocsExport = {
  kind: "SUPERDOCS_EXPORT";
  mode: string;
  document_id: string;
  export_id: string | null;
  format: string | null;
  filename: string;
  approved_change_ids: string[];
  download_url: string | null;
  storage_key: string | null;
  size: number | null;
  sha256: string | null;
  retrieved_at: string;
  note?: string;
};

export type SuperDocsLedger = {
  mode: string;
  working_document_id: string | null;
  source_document_ids: string[];
  export: SuperDocsExport | null;
  coverage: {
    complete: boolean;
    operations: Array<{ operation: string; exercised: boolean; count: number; failures: number }>;
  };
  operations: SuperDocsOperation[];
};

export type GeneratedArtifact = {
  id: string;
  name: string;
  kind: string;
  content_type: string;
  storage_key: string;
  size: number;
  sha256: string;
  generated_at: string;
  description: string;
};

export type SignoffItem = {
  id: string;
  role: string;
  person: string | null;
  status: "PENDING" | "APPROVED";
  signed_at: string | null;
  signed_by: string | null;
};

export type AuditEvent = {
  id: string;
  event: string;
  actor: string;
  actor_id: string | null;
  detail: string;
  created_at: string;
};

export type ApiReadiness = {
  ready_for_generation: boolean;
  ready_for_close: boolean;
  readiness: number;
  documents: { required: number; present: number; missing_types: string[]; unclassified: number };
  checklist: { required: number; complete: number };
  generation: { generated: boolean };
  reviews: { total: number; resolved: number };
  signoffs: { required: number; approved: number };
  export: { exported: boolean };
  blockers: string[];
};

export type CloseDetail = {
  id: string;
  entity: string;
  period: string;
  owner: string;
  due_date: string;
  template_id: string;
  template_name: string;
  required_document_types: string[];
  status: CloseStatus;
  created_at: string;
  created_by: string;
  closed_at: string | null;
  closed_by: string | null;
  generating: boolean;
  exported: boolean;
  export: ExportStatus["export"];
  superdocs_document_ids: string[];
  superdocs_working_document_id: string | null;
  superdocs_export: SuperDocsExport | null;
  generated_artifacts: GeneratedArtifact[];
  documents: DocumentItem[];
  checklist: ChecklistItem[];
  reviews: ReviewItem[];
  signoffs: SignoffItem[];
  audit: AuditEvent[];
  readiness: ApiReadiness;
};

export type GenerationJob = {
  id: string;
  close_id: string;
  status: "RUNNING" | "SUCCEEDED" | "FAILED";
  stage: string;
  stage_index: number;
  stages: string[];
  attempt: number;
  error: string | null;
  started_by: string;
  started_at: string;
  completed_at: string | null;
};

export type ExportStatus = {
  exported: boolean;
  export: { kind: string; filename: string; size: number; generated_at: string; files: string[] } | null;
  superdocs_export: SuperDocsExport | null;
  planned_files: string[];
};

export type Session = {
  token: string;
  user: { id: string; name: string; role: string };
};

/** A close template: the document types, controls and sign-offs a close is built from. */
export type Template = {
  id: string;
  name: string;
  required_document_types: string[];
  checklist_items: number;
  signoffs: string[];
};
