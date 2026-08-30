/**
 * SuperDocs Document Reality Engine — domain model.
 *
 * A document is not a file, it is a claim graph: text sections make claims,
 * claims are backed (or not) by evidence, requirements govern what the
 * document must contain, risks summarize what could go wrong, and every
 * state change is captured as a review event so the document's history can
 * be reconstructed.
 *
 * The main aggregate is named `SDDocument` rather than `Document` to avoid
 * shadowing the DOM's global `Document` type throughout the codebase.
 *
 * Derived numbers (compliance %, risk level, confidence) are intentionally
 * NOT stored on these records — they are computed by `src/domain/*` from
 * the underlying facts below, so the "why" behind every score is always
 * traceable. See src/domain/README (in ARCHITECTURE.md) for the pipeline.
 */

export type DocumentType =
  | "Vendor Agreement"
  | "Policy"
  | "Security Assessment"
  | "Compliance Letter"
  | "Legal Agreement";

export type DocumentStatus = "Draft" | "In Review" | "Approved" | "Published" | "Deprecated";

export type RiskLevel = "Low" | "Medium" | "High" | "Critical";

export type VerificationStatus =
  | "Verified"
  | "Partially Supported"
  | "Unverified"
  | "Contradicted"
  | "Needs Review";

export type EvidenceStrength = "Strong" | "Moderate" | "Weak";

export type EvidenceSourceType =
  | "Certification"
  | "Audit Report"
  | "Internal Data"
  | "Policy Document"
  | "Contract Clause"
  | "Test Result"
  | "Attestation"
  | "External Registry";

export type RequirementStatus = "Satisfied" | "Warning" | "Failed";

export type RequirementCategory =
  | "Mandatory Section"
  | "Required Terminology"
  | "Formatting"
  | "Citation"
  | "Policy"
  | "Translation"
  | "Metadata"
  | "Approval";

export type RiskCategory =
  | "Unsupported Claim"
  | "Conflicting Statement"
  | "Stale Evidence"
  | "Missing Evidence"
  | "Rule Violation"
  | "Unresolved Review"
  | "High-Impact Change"
  | "Incomplete Approval";

export type RiskStatus = "Open" | "Mitigated" | "Accepted";

export type ActionStatus = "Open" | "In Progress" | "Done";
export type ActionPriority = "Low" | "Medium" | "High";

export type DecisionOutcome = "Approved" | "Rejected" | "Deferred" | "Conditional";

export type ReviewEventType =
  | "Document Created"
  | "Evidence Attached"
  | "Claim Verified"
  | "Claim Contradicted"
  | "Requirement Failed"
  | "Requirement Satisfied"
  | "Reviewer Assigned"
  | "Comment Added"
  | "Content Changed"
  | "Risk Recalculated"
  | "Evidence Marked Stale"
  | "Approval Requested"
  | "Approval Granted"
  | "Changes Requested"
  | "Finding Resolved"
  | "Action Assigned"
  | "Action Completed";

export type ReviewTargetType = "Claim" | "Evidence" | "Requirement" | "Risk" | "Section" | "Document" | "Action" | "Decision";

export interface Person {
  name: string;
  role: string;
}

export interface Section {
  id: string;
  documentId: string;
  order: number;
  heading: string;
  /** Paragraphs joined by \n\n — the document's own words, rendered in the reading pane. */
  body: string;
  claimIds: string[];
}

export interface Evidence {
  id: string;
  documentId: string;
  title: string;
  description: string;
  sourceType: EvidenceSourceType;
  sourceName: string;
  /** Internal reference number/citation — never a live external link in this demo. */
  reference?: string;
  strength: EvidenceStrength;
  /** ISO date the evidence was produced or collected. */
  collectedAt: string;
  /** ISO date the evidence expires, if it has an explicit validity window. */
  expiresAt?: string;
  /**
   * A reviewer can flag evidence as stale (or vouch it as still current) based on
   * judgment the collected/expiry dates alone don't capture. Checked before the
   * automatic date-based rule in `domain/evidence.ts`.
   */
  reviewerOverride?: "Stale" | "Fresh";
  linkedClaimIds: string[];
}

export interface Claim {
  id: string;
  documentId: string;
  sectionId: string;
  text: string;
  /** Who or what makes the claim, e.g. "Ironclad Cloud Services", "Section 4.2". */
  claimant: string;
  evidenceIds: string[];
  verificationStatus: VerificationStatus;
  /** 0–100 model/reviewer confidence in the claim as currently evidenced. */
  confidence: number;
  lastVerifiedAt?: string;
  reviewer?: string;
  contradictionNote?: string;
}

export interface Requirement {
  id: string;
  documentId: string;
  category: RequirementCategory;
  description: string;
  status: RequirementStatus;
  /** Why the status is what it is — required, never just a bare pass/fail. */
  explanation: string;
  relatedSectionId?: string;
  severity: "Low" | "Medium" | "High";
}

export interface Risk {
  id: string;
  documentId: string;
  category: RiskCategory;
  title: string;
  description: string;
  severity: RiskLevel;
  status: RiskStatus;
  detectedAt: string;
  relatedClaimIds: string[];
  relatedRequirementIds: string[];
  relatedEvidenceIds: string[];
}

export interface Decision {
  id: string;
  documentId: string;
  description: string;
  outcome: DecisionOutcome;
  decidedBy: string;
  decidedAt: string;
  relatedReviewEventId?: string;
  notes?: string;
}

export interface ActionItem {
  id: string;
  documentId: string;
  title: string;
  description: string;
  assignee: string;
  status: ActionStatus;
  priority: ActionPriority;
  dueDate: string;
  relatedRiskId?: string;
  relatedRequirementId?: string;
}

export interface ChangeEvent {
  id: string;
  documentId: string;
  fromVersion: string;
  toVersion: string;
  occurredAt: string;
  author: string;
  summary: string;
  textChangeCount: number;
  claimChangeIds: string[];
  requirementChangeIds: string[];
  evidenceChangeIds: string[];
  /** Net new open risks introduced by this change (negative = net risks resolved). */
  riskDelta: number;
  highlights: string[];
}

export interface ReviewComment {
  id: string;
  documentId: string;
  targetType: ReviewTargetType;
  targetId: string;
  author: string;
  text: string;
  createdAt: string;
}

export interface ReviewEvent {
  id: string;
  documentId: string;
  timestamp: string;
  actor: string;
  type: ReviewEventType;
  affectedType: ReviewTargetType;
  affectedId: string;
  explanation: string;
}

export interface ProvenanceRecord {
  id: string;
  subjectType: "Claim" | "Evidence" | "Document";
  subjectId: string;
  /** e.g. "Vendor-submitted", "Internal review", "Public registry". */
  origin: string;
  occurredAt: string;
  actor: string;
  transformation: string;
}

export interface SDDocument {
  id: string;
  title: string;
  type: DocumentType;
  version: string;
  status: DocumentStatus;
  owner: Person;
  counterparty?: string;
  createdAt: string;
  updatedAt: string;
  effectiveDate?: string;
  annualValue?: number;
  sections: Section[];
  claims: Claim[];
  requirements: Requirement[];
  evidence: Evidence[];
  risks: Risk[];
  decisions: Decision[];
  actions: ActionItem[];
  changes: ChangeEvent[];
  reviewEvents: ReviewEvent[];
  comments: ReviewComment[];
  provenance: ProvenanceRecord[];
}
