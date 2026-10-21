export type CorpusSummary = {
  corpus_id: string;
  organization: string;
  description: string;
  role_count: number;
  analyzed: boolean;
  roles: Array<{ role_id: string; title: string; team: string; filename: string }>;
};

export type ArchitectureMetrics = {
  total_roles: number;
  proposed_families: number;
  tracks: number;
  strong_fits: number;
  provisional: number;
  misfits: number;
  unclustered: number;
  bridge_roles: number;
};

export type ClusterMember = {
  role_id: string;
  title: string;
  cohesion: number;
  nearest_other_cluster_id: string | null;
  nearest_other_similarity: number | null;
  is_ambiguous: boolean;
};

export type Cluster = {
  cluster_id: string;
  proposed_family: string | null;
  member_role_ids: string[];
  members: ClusterMember[];
  cohesion: number;
  nearest_cluster_id: string | null;
  nearest_cluster_similarity: number | null;
  separation: number | null;
  ambiguous_role_ids: string[];
  label_confidence: number | null;
  notes: string;
};

export type TitleConflict = {
  kind: "title_seniority_overstates_evidence" | "title_management_conflict" | "title_understates_scope";
  summary: string;
  title_signal: string;
  evidence_result: string;
};

export type ArchitectureSummary = {
  corpus_id: string;
  organization: string;
  metrics: ArchitectureMetrics;
  families: Array<{ id: string; name: string; description: string }>;
  tracks: Array<{ id: string; name: string; kind: string; description: string }>;
  clusters: Cluster[];
  unclustered_role_ids: string[];
  bridge_role_ids: string[];
  title_conflicts: Array<{
    role_id: string;
    title: string;
    fit_status: string;
    proposed_level: string | null;
    proposed_track: string | null;
    title_conflict: TitleConflict;
  }>;
};

export type RoleDetail = {
  role_id: string;
  title: string;
  team: string;
  organization: string;
  filename: string | null;
  proposed_family: string | null;
  career_track: string | null;
  level: string | null;
  fit_status: string;
  confidence: number;
  supporting_evidence: string[];
  counter_evidence: string[];
  misfit_reasons: Array<{ code: string; summary: string; detail: string }>;
  source_references: Array<{ document_id: string; locator: string; excerpt?: string }>;
  signals: Record<string, string>;
  cluster_id: string | null;
  profile_id: string | null;
  title_conflict: TitleConflict | null;
};

export type ExceptionCard = {
  role_id: string;
  title: string;
  bucket: string;
  fit_status: string;
  confidence: number;
  proposed_family: string | null;
  proposed_track: string | null;
  proposed_level: string | null;
  why: string;
  reasons: Array<{ code: string; summary: string; detail: string }>;
  supporting_evidence: string[];
  counter_evidence: string[];
  nearest_cluster_id: string | null;
  nearest_similarity: number | null;
  status: string;
  has_normalized_profile: boolean;
};

export type FrameworkPayload = {
  organization: string;
  purpose: string;
  principles: string[];
  tracks: Array<{ id: string; name: string; kind: string; description: string }>;
  levels: Array<{
    id: string;
    label: string;
    track_id: string;
    version: number;
    scope: string;
    autonomy_decision: string;
    complexity: string;
    impact: string;
    leadership: string;
    people_management: string;
  }>;
  families: Array<{ id: string; name: string; description: string }>;
  competency_matrices: Array<{
    family_id: string;
    family_name: string;
    evidence_limited: boolean;
    limitation: string;
    competencies: Array<{ id: string; name: string; description: string }>;
  }>;
  role_mappings: Array<{
    role_id: string;
    fit_status: string;
    family_id: string | null;
    track_id: string | null;
    level_id: string | null;
    profile_id: string | null;
  }>;
  provisional_summary: Array<{ role_id: string; title: string; summary: string; fit_status: string }>;
  misfit_summary: Array<{ role_id: string; title: string; summary: string; fit_status: string }>;
  profile_count: number;
  default_occupied_level_id: string | null;
  editable_dimensions: string[];
};

export type ProfileSummary = {
  profile_id: string;
  role_id: string;
  display_title: string;
  family_name: string;
  track_name: string;
  level_label: string;
  classification: string;
  is_provisional: boolean;
};

export type ProfileDetail = ProfileSummary & {
  role_purpose: string;
  responsibilities: string[];
  scope_decision_making: string;
  core_competencies: string;
  level_expectations: string;
  progression: string;
  source_evidence_note: string;
  kind?: string;
  title?: string;
  summary?: string;
  normalized_profile?: boolean;
  message?: string;
};

export type ImpactPayload = {
  level_id: string;
  level_label: string;
  changed_dimensions: string[];
  affected_profiles_count: number;
  unaffected_profiles_count: number;
  affected_profile_ids: string[];
  unaffected_profile_ids: string[];
  affected_sections: Array<{ profile_id: string; section_id: string; reason: string; edge_id: string }>;
  reason: string;
  old_level: { scope: string; [key: string]: unknown };
  new_level: { scope: string; [key: string]: unknown };
};

export type UpdatePlanView = {
  plan_id: string;
  profile_id: string;
  section_id: string;
  before: string;
  after: string;
  reason: string;
  status: string;
  preserved_rendered_fields: string[];
  changed_rendered_fields: string[];
  dependency: { id: string; source_id: string; source_version: number; target_id: string };
  decision?: boolean | null;
};

export type ReviewPayload = {
  empty?: boolean;
  corpus_id?: string;
  remote_operation: string;
  review_outcome: string;
  mutation_applied: boolean;
  domain_applied: boolean;
  plans: UpdatePlanView[];
  impact?: ImpactPayload;
  preservation?: {
    ok: boolean;
    unrelated_sections_preserved: boolean;
    unchanged_section_count: number;
    changed_section_count: number;
    violations: string[];
  } | null;
  message?: string;
};

export type SuperDocsStatus = {
  configured: boolean;
  offline_demo: boolean;
  live_export_available: boolean;
  live_export_reason: string;
  live: { present: boolean; completed_steps?: string[]; workflow?: string; domain_applied?: boolean };
};
