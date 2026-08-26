// Mirrors src/domain and src/compliance types on the CLI side. Kept as a
// separate declaration rather than a shared import: this is a browser
// bundle reading static JSON, not a Node process sharing runtime code with
// the CLI.

export type RequirementFrequency = "continuous" | "annual" | "on_change" | "on_onboarding";
export type RequirementScope = "all_clients" | "firm" | "advisory_clients";

export interface Requirement {
  id: string;
  citation: string;
  title: string;
  obligation: string;
  evidence_expected: string[];
  frequency: RequirementFrequency;
  applies_to: RequirementScope;
}

export interface Client {
  id: string;
  name: string;
  onboarded_on: string;
  advisory_type: string;
  ai_assisted: boolean;
  agreement_version: string;
  risk_profile_reviewed_on: string | null;
}

export type CoverageStatus = "EVIDENCED" | "STALE" | "MISSING" | "INCONSISTENT";

export interface EvidenceRef {
  file: string;
  line: number;
  excerpt: string;
}

export interface CoverageEntry {
  requirement_id: string;
  client_id: string | null;
  status: CoverageStatus;
  detail: string;
  evidence: EvidenceRef[];
  method: "deterministic" | "model";
}

export interface CoverageSnapshot {
  generated_at: string | null;
  notes_dir: string | null;
  summary: Partial<Record<CoverageStatus, number>>;
  entries: CoverageEntry[];
}

export interface PlannedPackSection {
  requirement_id: string;
  title: string;
  heading: string;
  status: CoverageStatus;
}

export interface PackManifestEntry {
  client_id: string;
  client_name: string;
  title: string;
  documentId: string;
  durableDocumentId: string | null;
  sessionId: string;
  verified: boolean;
  plannedSections: PlannedPackSection[];
  exportedFiles: string[];
  generated_at: string;
}

export interface PacksSnapshot {
  generated_at: string | null;
  packs: PackManifestEntry[];
}

export interface TemplateVersion {
  template_id: string;
  version: string;
  effective_from: string;
  requirement_ids: string[];
  content_hash: string;
  superseded_by: string | null;
}

export interface ClientVersionRecord {
  client_id: string;
  template_id: string;
  version: string;
  issued_on: string;
  consented_on: string | null;
  consent_evidence: string | null;
}

export interface VersionStore {
  template_versions: TemplateVersion[];
  client_versions: ClientVersionRecord[];
}

export type ConsentCellStatus =
  | "CURRENT_CONSENTED"
  | "CURRENT_PENDING_CONSENT"
  | "BEHIND"
  | "BEHIND_NOT_CONSENTED"
  | "NOT_ISSUED";

export interface ConsentCell {
  template_id: string;
  version: string | null;
  current_version: string | null;
  status: ConsentCellStatus;
  consented_on: string | null;
  consent_evidence: string | null;
}

export interface ConsentMatrixRow {
  client_id: string;
  client_name: string;
  cells: ConsentCell[];
}

export interface ConsentMatrix {
  generated_at: string | null;
  templates: string[];
  rows: ConsentMatrixRow[];
}

export type AmendmentKind = "new_requirement" | "changed_obligation";

export interface AmendmentNotice {
  client_id: string;
  client_name: string;
  template_id: string;
  requirement_id: string;
  previous_version: string;
  new_version: string;
  citation: string;
  previous_text: string;
  new_text: string;
  what_client_must_do: string;
  what_did_not_change: string[];
  consent_status: "pending";
}

export interface AmendmentScope {
  event: unknown;
  affected_template_ids: string[];
  affected_client_ids: string[];
}

export interface AmendmentEvent {
  requirement_id: string;
  kind: AmendmentKind;
  effective_from: string;
  scope: AmendmentScope;
  notices: AmendmentNotice[];
}

/** A structured batch (event.json present) or a raw one (older .md-only notices, read verbatim). */
export type AmendmentBatch =
  | { event_dir: string; structured: true; event: AmendmentEvent }
  | {
      event_dir: string;
      structured: false;
      requirement_id: string;
      effective_from: string | null;
      notices_raw: { client_id: string; filename: string; content: string }[];
    };

export interface LedgerRow {
  label: string;
  opsCharged: number;
  runningTotal: number;
  monthlyRemaining: number | null;
}

export interface LedgerSnapshot {
  command: string;
  generated_at: string;
  ops_cap: number;
  total_spent: number;
  remaining: number | null;
  rows: LedgerRow[];
}
