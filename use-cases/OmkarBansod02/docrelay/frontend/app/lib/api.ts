const API_BASE = process.env.NEXT_PUBLIC_DOCRELAY_API_URL ?? "http://localhost:8000";

export type ConnectionStatus = "PENDING" | "CONNECTED" | "DISCONNECTED" | "REAUTH_REQUIRED" | "INVALID";

export interface GoogleConnection {
  connection_id: string;
  provider: "GOOGLE";
  status: ConnectionStatus;
  granted_scopes: string[];
  watch_authorized?: boolean;
  last_validated_at: string | null;
  disconnected_at: string | null;
}

export interface ConnectionsResponse {
  oauth_configured: boolean;
  selected_scopes: string[];
  connections: GoogleConnection[];
}

export type FrozenPreviewKind = "paragraph" | "heading";

export interface FrozenPreviewBlock {
  kind: FrozenPreviewKind;
  named_style: string | null;
  text: string;
}

export interface FrozenDocumentPreview {
  available: boolean;
  revision_id: string;
  blocks: FrozenPreviewBlock[];
}

export interface SourceRegistration {
  source: {
    source_id: string;
    provider_file_id: string;
    name: string;
    mime_type: string;
    parent_ids: string[];
  };
  baseline: {
    capture_id: string;
    revision_id: string;
    native_canonical_sha256: string;
    docx_sha256: string;
    docx_size_bytes: number;
  };
  preview?: FrozenDocumentPreview;
}

/** One canonical source document DocRelay has registered for a connection. */
export interface RegisteredSource {
  source_id: string;
  provider_file_id: string;
  name: string;
  mime_type: string;
  last_seen_at: string | null;
}

export type WriteAuthorizationState = "REQUIRED" | "AUTHORIZED";
export type MachineWriteBackStatus =
  | "NOT_READY"
  | "AWAITING_REVIEW"
  | "WRITE_AUTHORIZATION_REQUIRED"
  | "READY"
  | "IN_PROGRESS"
  | "WRITE_VERIFIED"
  | "CONFLICT"
  | "UNKNOWN"
  | "ATTENTION"
  | "VERIFICATION_FAILED"
  | "FAILED"
  | "CANCELLED"
  | "REVIEW_LATEST";

export interface ConflictSummary {
  detection_stage: string;
  baseline_revision_id: string;
  latest_revision_id: string | null;
  decision: ConflictChoice | null;
}

export interface RunSummary {
  run_id: string;
  watch_id: string | null;
  originating_scan_id: string | null;
  source_id: string;
  provider_file_id: string;
  document_name: string;
  instruction: string | null;
  proposal_count: number;
  provider_version: string | null;
  source_revision_id: string;
  matched_rule_id: string | null;
  matched_rule_version: number | null;
  workflow_state: SyncRunState;
  review_status: "NOT_READY" | "AWAITING_DECISIONS" | "AWAITING_CONTINUE" | "DECISIONS_SUBMITTED" | "REVIEWED" | "FAILED";
  write_authorization_status: WriteAuthorizationState | null;
  dry_run_status: "NOT_REQUESTED" | "READY";
  write_back_status: MachineWriteBackStatus;
  verification_status: "PASSED" | "FAILED" | null;
  last_error_code: string | null;
  conflict: ConflictSummary | null;
  ready_for_dry_run: boolean;
  ready_for_write_back: boolean;
  export: ExportView | null;
  started_at: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  external_effect_count: number;
  external_effect_attempt_count: number;
  external_effects_unknown: number;
  superdocs_usage: Record<string, unknown>;
}

export interface WatchRoot {
  watch_id: string;
  connection_id: string;
  root_folder_id: string;
  root_name: string;
  enabled: boolean;
  schedule: string;
  interval_seconds: number;
  timezone: string;
  last_scan_at: string | null;
  last_successful_scan_at: string | null;
  next_scan_at: string | null;
  last_scan_status: "RUNNING" | "SUCCEEDED" | "FAILED" | null;
  last_error_code: string | null;
}

export interface WatchRule {
  rule_id: string;
  watch_id: string;
  folder_id: string;
  folder_name: string;
  version: number;
  instruction: string;
  instruction_sha256: string;
  enabled: boolean;
  precedence: "nearest_enabled_ancestor";
}

export interface WatchScan {
  scan_id: string;
  watch_id: string;
  trigger: "SCHEDULED" | "MANUAL";
  status: "RUNNING" | "SUCCEEDED" | "FAILED";
  claim_generation: number;
  started_at: string;
  completed_at: string | null;
  discovered_count: number;
  changed_count: number;
  unchanged_count: number;
  enqueued_count: number;
  skipped_count: number;
  failed_count: number;
  failure_code: string | null;
}

export interface WatchScanItem {
  provider_file_id: string;
  provider_version: string | null;
  name: string;
  mime_type: string;
  ancestor_folder_ids: string[];
  discovery_kind: string;
  outcome: "ENQUEUED" | "UNCHANGED" | "NO_RULE" | "UNSUPPORTED" | "FAILED" | "OUT_OF_SCOPE";
  reason_code: string | null;
  matched_rule_id: string | null;
  matched_rule_version: number | null;
  run_id: string | null;
}

export type SyncRunState =
  | "QUEUED"
  | "BASELINING"
  | "EDITING"
  | "AWAITING_REVIEW"
  | "REVIEWED_EXPORT_READY"
  | "READY_TO_COMMIT"
  | "PREVIEW_READY"
  | "COMMITTING"
  | "VERIFYING"
  | "SUCCEEDED"
  | "CONFLICT"
  | "UNSUPPORTED"
  | "SKIPPED"
  | "EXPIRED"
  | "COMMIT_OUTCOME_UNKNOWN"
  | "VERIFICATION_FAILED"
  | "FAILED"
  | "CANCELLED";

export interface ProposalView {
  proposal_id: string;
  review_round: number;
  change_id: string;
  operation: string;
  chunk_id: string | null;
  document_id: string;
  old_html: string | null;
  new_html: string | null;
  ai_explanation: string | null;
  replaces_proposal_id: string | null;
  decision: "APPROVE" | "REJECT" | null;
  feedback: string | null;
}

export interface ExportView {
  export_id: string;
  artifact_reference: string;
  sha256: string;
  size_bytes: number;
  content_type: string;
  content_disposition: string | null;
  warnings: Record<string, unknown>[];
  final_version_id: string | null;
  exported_at: string;
}

export interface RunView {
  run_id: string;
  source_id: string;
  provider_revision_id: string;
  state: SyncRunState;
  attention_code: string | null;
  provider_read_error?: {
    code: string;
    operation: "jobs.get";
    retryable: true;
    observed_at: string;
    occurrence_count: number;
    provider_request_id?: string | null;
  } | null;
  session_id: string | null;
  session_document_id: string | null;
  durable_document_id: string | null;
  upload_version_id: string | null;
  final_version_id: string | null;
  provider_job_id: string | null;
  provider_job_status: string | null;
  awaiting_kind: string | null;
  pending_proposals: ProposalView[];
  export: ExportView | null;
  write_back: WriteBackRunSummary | null;
}

export interface WriteBackRunSummary {
  status: WriteBackStatus;
  write_plan_id?: string;
  write_plan_sha256?: string;
  preview?: {
    old_text: string;
    new_text: string;
    context: DryRunView["context"];
    changes?: Array<{
      proposal_id?: string | null;
      old_text: string;
      new_text: string;
      context: DryRunView["context"];
    }>;
  } | null;
  backup_created: boolean;
  backup_verified: boolean;
  write_applied: boolean;
  structurally_verified: boolean;
  resulting_revision_id: string | null;
  conflict_detection_stage: string | null;
  conflict_decision: ConflictChoice | null;
}

export type DryRunStatus = "READY" | "UNSUPPORTED" | "AMBIGUOUS" | "STALE" | "NOT_APPROVED";

export interface DryRunSource {
  provider: "GOOGLE";
  file_id: string;
  baseline_revision_id: string;
  native_snapshot_sha256: string;
}

export interface DryRunMappedChange {
  proposal_id: string;
  old_text: string;
  new_text: string;
  context: DryRunView["context"];
  structural_location: Record<string, unknown>;
}

export interface DryRunView {
  run_id: string;
  proposal_id: string | null;
  status: DryRunStatus;
  source: DryRunSource | null;
  old_text: string | null;
  new_text: string | null;
  context?: {
    offset_unit: "UNICODE_CODE_POINT";
    before: ContextSpan;
    after: ContextSpan;
    source_snapshot_id: string;
    native_snapshot_sha256: string;
  } | null;
  changes?: DryRunMappedChange[];
  structural_location: Record<string, unknown> | null;
  operation_count: number;
  operation_types: string[];
  provider_operation: Record<string, unknown> | null;
  why_safe: string[];
  mapping_proof_id: string | null;
  mapping_proof_sha256: string | null;
  write_plan_id: string | null;
  write_plan_sha256: string | null;
  reason_code: string | null;
  reason: string | null;
  candidate_count: number | null;
  cloud_mutation_performed: false;
}

export interface ContextSpan {
  text: string;
  highlight_start: number;
  highlight_end: number;
}

export type WriteBackStatus =
  | "READY"
  | "IN_PROGRESS"
  | "WRITE_VERIFIED"
  | "CONFLICT"
  | "ATTENTION"
  | "VERIFICATION_FAILED"
  | "FAILED"
  | "CANCELLED"
  | "REVIEW_LATEST";

export type ConflictChoice = "CANCEL" | "REVIEW_LATEST";

export interface WriteConflictView {
  baseline_revision_id: string;
  latest_revision_id: string | null;
  detection_stage: string;
  detected_at: string;
  backup_created: boolean;
  decision: ConflictChoice | null;
}

export interface WriteBackView {
  run_id: string;
  status: WriteBackStatus;
  write_plan_id: string;
  write_plan_sha256: string;
  backup_created: boolean;
  backup_verified: boolean;
  source_revision_verified: boolean;
  write_applied: boolean;
  structurally_verified: boolean;
  baseline_revision_id: string;
  resulting_revision_id: string | null;
  verified_preview?: FrozenDocumentPreview | null;
  attention_code: string | null;
  conflict: WriteConflictView | null;
  preview?: WriteBackRunSummary["preview"];
}

class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ValidationIssue = {
  loc?: unknown;
  msg?: unknown;
  message?: unknown;
};

function formatValidationIssue(issue: ValidationIssue): string | null {
  const message = typeof issue.msg === "string"
    ? issue.msg
    : typeof issue.message === "string"
      ? issue.message
      : null;
  if (!message) return null;

  const location = Array.isArray(issue.loc)
    ? issue.loc.filter((part): part is string | number => typeof part === "string" || typeof part === "number").join(" → ")
    : "";
  return location ? `${location}: ${message}` : message;
}

export function formatApiError(body: unknown, status: number): string {
  if (typeof body === "string" && body.trim()) return body;
  if (!body || typeof body !== "object") return `Request failed (${status})`;

  const payload = body as {
    error?: { message?: unknown };
    detail?: unknown;
  };
  const configuredMessage = payload.error?.message;
  if (typeof configuredMessage === "string" && configuredMessage.trim()) return configuredMessage;
  if (typeof payload.detail === "string" && payload.detail.trim()) return payload.detail;
  if (Array.isArray(payload.detail)) {
    const issues = payload.detail
      .filter((item): item is ValidationIssue => Boolean(item) && typeof item === "object")
      .map(formatValidationIssue)
      .filter((message): message is string => message !== null);
    if (issues.length > 0) return issues.join("; ");
  }
  if (payload.detail && typeof payload.detail === "object") {
    const issue = formatValidationIssue(payload.detail as ValidationIssue);
    if (issue) return issue;
  }
  return `Request failed (${status})`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const code = (body as { error?: { code?: unknown } } | null)?.error?.code;
    throw new ApiError(
      res.status,
      typeof code === "string" ? code : "UNKNOWN",
      formatApiError(body, res.status),
    );
  }
  return res.json() as Promise<T>;
}

export function getConnections(signal?: AbortSignal): Promise<ConnectionsResponse> {
  return request<ConnectionsResponse>("/api/v1/google/connections", { signal, cache: "no-store" });
}

export function getAuthorizeUrl(profile: "single_file" | "watch" = "single_file"): string {
  const url = new URL(`${API_BASE}/api/v1/google/oauth/authorize`);
  if (profile === "watch") url.searchParams.set("profile", "watch");
  return url.toString();
}

export function registerSource(
  connectionId: string,
  fileId: string,
  signal?: AbortSignal,
): Promise<SourceRegistration> {
  return request<SourceRegistration>(
    `/api/v1/google/connections/${connectionId}/sources`,
    { method: "POST", body: JSON.stringify({ file_id: fileId }), signal },
  );
}

/** Read-only projection of the registered sources. Never touches Google. */
export function listSources(
  connectionId: string,
  signal?: AbortSignal,
): Promise<{ connection_id: string; sources: RegisteredSource[] }> {
  return request<{ connection_id: string; sources: RegisteredSource[] }>(
    `/api/v1/google/connections/${connectionId}/sources`,
    { signal, cache: "no-store" },
  );
}

export function startRun(payload: {
  source_id: string;
  baseline_capture_id: string;
  instruction: string;
}): Promise<RunView> {
  return request<RunView>("/api/v1/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getRun(runId: string, signal?: AbortSignal): Promise<RunView> {
  return request<RunView>(`/api/v1/runs/${runId}`, { signal, cache: "no-store" });
}

export function listRuns(signal?: AbortSignal): Promise<{ runs: RunSummary[] }> {
  return request<{ runs: RunSummary[] }>("/api/v1/runs", { signal, cache: "no-store" });
}

export function getRunSummary(runId: string, signal?: AbortSignal): Promise<RunSummary> {
  return request<RunSummary>(`/api/v1/runs/${runId}/summary`, { signal, cache: "no-store" });
}

export function listProposals(runId: string, signal?: AbortSignal): Promise<{ run_id: string; proposals: ProposalView[] }> {
  return request<{ run_id: string; proposals: ProposalView[] }>(`/api/v1/runs/${runId}/proposals`, { signal, cache: "no-store" });
}

export function resumeRun(runId: string): Promise<RunView> {
  return request<RunView>(`/api/v1/runs/${runId}/resume`, { method: "POST" });
}

export function submitDecisions(
  runId: string,
  decisions: { proposal_id: string; approve: boolean; feedback?: string | null }[],
): Promise<RunView> {
  if (typeof runId !== "string" || runId.trim() === "" || runId === "undefined") {
    throw new Error("The current run ID is unavailable; decisions were not submitted.");
  }
  return request<RunView>(`/api/v1/runs/${runId}/decisions`, {
    method: "POST",
    body: JSON.stringify({ decisions }),
  });
}

export function submitContinue(runId: string, shouldContinue: boolean): Promise<RunView> {
  return request<RunView>(`/api/v1/runs/${runId}/continue`, {
    method: "POST",
    body: JSON.stringify({ should_continue: shouldContinue }),
  });
}

export function createDryRun(runId: string, proposalId?: string): Promise<DryRunView> {
  return request<DryRunView>(`/api/v1/runs/${runId}/dry-run`, {
    method: "POST",
    body: proposalId ? JSON.stringify({ proposal_id: proposalId }) : "{}",
  });
}

export function writeBackSafely(runId: string): Promise<WriteBackView> {
  return request<WriteBackView>(`/api/v1/runs/${runId}/write-back`, {
    method: "POST",
  });
}

export function decideWriteConflict(
  runId: string,
  choice: ConflictChoice,
): Promise<WriteBackView> {
  return request<WriteBackView>(`/api/v1/runs/${runId}/conflict-decision`, {
    method: "POST",
    body: JSON.stringify({ choice }),
  });
}

export function verifyWriteAuthorization(runId: string, fileId: string): Promise<{
  run_id: string;
  state: WriteAuthorizationState;
  checked_at: string;
  action: "AUTHORIZE_THIS_DOCUMENT_FOR_WRITE_BACK";
}> {
  return request(`/api/v1/runs/${runId}/write-authorization`, {
    method: "POST",
    body: JSON.stringify({ file_id: fileId }),
  });
}

export function listWatches(signal?: AbortSignal): Promise<{ watches: WatchRoot[] }> {
  return request<{ watches: WatchRoot[] }>("/api/v1/watches", { signal, cache: "no-store" });
}

export function configureWatch(payload: {
  connection_id: string;
  root_folder_id: string;
  interval_seconds: number;
  enabled: boolean;
}): Promise<WatchRoot> {
  return request<WatchRoot>("/api/v1/watches", { method: "POST", body: JSON.stringify(payload) });
}

export function updateWatchSchedule(
  watchId: string,
  payload: { enabled: boolean; interval_seconds: number },
): Promise<WatchRoot> {
  return request<WatchRoot>(`/api/v1/watches/${watchId}/schedule`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listWatchRules(watchId: string, signal?: AbortSignal): Promise<{ rules: WatchRule[] }> {
  return request<{ rules: WatchRule[] }>(`/api/v1/watches/${watchId}/rules`, { signal, cache: "no-store" });
}

export function configureWatchRule(
  watchId: string,
  payload: { folder_id: string; instruction: string; enabled: boolean },
): Promise<WatchRule> {
  return request<WatchRule>(`/api/v1/watches/${watchId}/rules`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listWatchScans(watchId: string, signal?: AbortSignal): Promise<{ scans: WatchScan[] }> {
  return request<{ scans: WatchScan[] }>(`/api/v1/watches/${watchId}/scans`, { signal, cache: "no-store" });
}

export function triggerWatchScan(watchId: string): Promise<WatchScan> {
  return request<WatchScan>(`/api/v1/watches/${watchId}/scans`, { method: "POST" });
}

export function listWatchScanItems(
  watchId: string,
  scanId: string,
  signal?: AbortSignal,
): Promise<{ items: WatchScanItem[] }> {
  return request<{ items: WatchScanItem[] }>(`/api/v1/watches/${watchId}/scans/${scanId}/items`, { signal, cache: "no-store" });
}

export function listWatchScanRuns(
  watchId: string,
  scanId: string,
  signal?: AbortSignal,
): Promise<{ runs: RunSummary[] }> {
  return request<{ runs: RunSummary[] }>(`/api/v1/watches/${watchId}/scans/${scanId}/runs`, { signal, cache: "no-store" });
}

export function listWatchRuns(watchId: string, signal?: AbortSignal): Promise<{ runs: RunSummary[] }> {
  return request<{ runs: RunSummary[] }>(`/api/v1/watches/${watchId}/runs`, { signal, cache: "no-store" });
}

export { ApiError };
