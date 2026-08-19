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
  awaiting_kind?: AwaitingKind;
  /** Arrives as a JSON-encoded string. Always read via parsePendingChanges. */
  pending_changes?: unknown;
  changes?: unknown;
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

/* ---------------------------------------------------------------- audit --- */

export type FindingKind =
  | "band_violation"
  | "unsupported_claim"
  | "dropped_reservation"
  | "injected_instruction";

export type FindingSeverity = "high" | "medium" | "low";

export interface CalibrationFinding {
  id: string;
  kind: FindingKind;
  severity: FindingSeverity;
  /** One line the writer reads first. */
  title: string;
  /** Why it fired and what to do about it. */
  detail: string;
  /** The text that triggered it, quoted from the letter or the intake. */
  excerpt?: string;
  source: "lexicon" | "verifier" | "injection-scan";
}

export interface VerifierResult {
  status: "ok" | "unavailable" | "failed";
  /** Band a cold reader would infer. Only set when status is "ok". */
  inferredBand?: StrengthBand;
  reason?: string;
  findings: CalibrationFinding[];
}

export interface AuditReport {
  declaredBand: StrengthBand;
  inferredBand?: StrengthBand;
  /** Positive means the letter reads warmer than declared. */
  drift?: number;
  findings: CalibrationFinding[];
  /**
   * Which checks ran. A check that did not run is stated, never implied to
   * have passed. "No findings" and "no checks" are different answers.
   */
  checks: {
    lexicon: "ran";
    reservations: "ran";
    injection: "ran";
    verifier: "ran" | "unavailable" | "failed";
  };
  verifierNote?: string;
  /** Milliseconds, per stage, so a run can report where the time went. */
  timings: Record<string, number>;
}

/* ---------------------------------------------------------------- usage --- */

export interface UsageStatus {
  tier?: string;
  operationsUsed?: number;
  operationsRemaining?: number;
  /** True when the remaining budget is too low to start another draft safely. */
  lowBudget: boolean;
}
