// lib/api.ts -- thin fetch wrapper around the FastAPI backend.
// Every function here maps 1:1 to an endpoint in backend/main.py, rebuilt
// on the Workspace -> Document -> DocumentVersion -> Section schema.
// There is no hardcoded pack anywhere -- every workspace, document, and
// reference is created through these calls, driven by a human.

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export type DocType = "policy" | "procedure";
export type WorkspaceStatus = "setup" | "analyzing" | "ready" | "needs_attention";
export type ReferenceStatus = "valid" | "needs_review" | "stale" | "needs_reanalysis" | "rejected";
export type SectionStatus = "active" | "needs_reanalysis" | "archived";
export type ProposedChangeStatus = "pending" | "approved" | "rejected" | "failed";
export type UpdateRequestStatus =
  | "processing" | "awaiting_review" | "approved" | "partially_approved" | "rejected";
export type FindingType = "conflict" | "broken_reference" | "outdated_reference" | "missing_reference" | "inconsistency";
export type FindingStatus = "open" | "resolved" | "dismissed";
export type AnalysisJobStatus = "pending" | "running" | "complete" | "failed";

export interface WorkspaceOut {
  id: string;
  organization_name: string;
  organization_type: string | null;
  pack_name: string;
  status: WorkspaceStatus;
  created_at: string;
  updated_at: string;
  policies?: number;
  procedures?: number;
}

export interface DocumentOut {
  id: string;
  workspace_id: string;
  doc_type: DocType;
  parent_policy_id: string | null;
  title: string;
  superdocs_document_id: string;
  superdocs_session_id: string;
  active_version_id: string | null;
  created_at: string;
  updated_at: string;
  sections?: SectionOut[];
  html?: string | null;
}

export interface SectionOut {
  id: string;
  document_id: string;
  parent_section_id: string | null;
  section_number: string;
  title: string;
  level: number;
  section_type: string | null;
  status: SectionStatus;
  chunk_id?: string;
  content_html?: string;
  content_text?: string;
  content_hash?: string;
}

export interface ReferenceOut {
  id: string;
  procedure_section_id: string;
  policy_section_id: string;
  relationship_type: string;
  confidence: number | null;
  evidence: string | null;
  status: ReferenceStatus;
  source: "llm_analysis" | "human";
  created_at: string;
  updated_at: string;
  policy_section?: SectionOut;
  policy_document_id?: string;
  procedure_section?: SectionOut;
  procedure_document_id?: string;
}

export interface FindingOut {
  id: string;
  finding_type: FindingType;
  source_section_id: string;
  target_section_id: string | null;
  reference_id: string | null;
  description: string;
  evidence: string | null;
  status: FindingStatus;
  created_at: string;
  resolved_at: string | null;
}

export interface ProposedChangeOut {
  id: string;
  update_request_id: string | null;
  document_id: string;
  section_id: string | null;
  base_version_id: string;
  reference_id: string | null;
  superdocs_job_id: string | null;
  old_html: string | null;
  new_html: string | null;
  ai_explanation: string | null;
  status: ProposedChangeStatus;
  reviewed_by: string | null;
  reviewed_at: string | null;
  feedback: string | null;
  resulting_version_id: string | null;
  created_at: string;
}

export interface ChangeEventOut {
  id: string;
  event_type: string;
  timestamp: string;
  document_id: string | null;
  document_version_id: string | null;
  section_id: string | null;
  reference_id: string | null;
  update_request_id: string | null;
  proposed_change_id: string | null;
  actor: string;
  description: string;
  approved: boolean | null;
}

export interface ReportSummary {
  documents: number;
  policies: number;
  procedures: number;
  references: number;
  references_valid: number;
  references_stale: number;
  references_needs_review: number;
  findings_open: number;
  pending_reviews: number;
  validation_overall_status: string;
}

export interface ReportOut {
  id: string;
  pack_version_label: string;
  generated_at: string;
  summary: ReportSummary;
}

export interface ValidationResult {
  validation_run_id: string;
  overall_status: "pass" | "fail";
  total_checks: number;
  passed: number;
  failed: number;
  checks: { check_type: string; reference_id: string | null; section_id: string | null; passed: boolean; details: string | null }[];
}

export interface AnalysisRunResult {
  run_id: string;
  jobs: { id: string; policy_document_id: string; procedure_document_id: string; status: AnalysisJobStatus; error_message: string | null }[];
  workspace_status: WorkspaceStatus;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // ignore
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // -- workspaces --------------------------------------------------------
  createWorkspace: (params: { organizationName: string; organizationType?: string; packName: string }) =>
    request<WorkspaceOut>("/workspaces", {
      method: "POST",
      body: JSON.stringify({
        organization_name: params.organizationName,
        organization_type: params.organizationType || null,
        pack_name: params.packName,
      }),
    }),
  listWorkspaces: () => request<WorkspaceOut[]>("/workspaces"),
  getWorkspace: (id: string) => request<WorkspaceOut>(`/workspaces/${id}`),
  deleteWorkspace: (id: string) =>
    request<{ status: string; workspace_id: string; workspace_name: string; deleted_documents: number }>(
      `/workspaces/${id}`,
      { method: "DELETE" }
    ),

  // -- documents -- upload is the only ingestion path, always human-triggered --
  uploadDocument: (workspaceId: string, params: {
    filename: string; fileBase64: string; docType: DocType; title: string; parentPolicyId?: string;
  }) =>
    request<{ document: DocumentOut; version: unknown; sections: SectionOut[] }>(
      `/workspaces/${workspaceId}/documents/upload`,
      {
        method: "POST",
        body: JSON.stringify({
          filename: params.filename,
          file_base64: params.fileBase64,
          doc_type: params.docType,
          title: params.title,
          parent_policy_id: params.parentPolicyId || null,
        }),
      }
    ),
  // Second creation path, alongside upload: ask the AI to draft a new
  // document from scratch, using this account's uploaded SuperDocs
  // templates as a starting point (see backend main.py's TEMPLATE_LIBRARY
  // and _ensure_templates_uploaded).
  draftDocument: (workspaceId: string, params: {
    docType: DocType; title: string; prompt: string; parentPolicyId?: string;
  }) =>
    request<{ document: DocumentOut; version: unknown; sections: SectionOut[] }>(
      `/workspaces/${workspaceId}/documents/draft`,
      {
        method: "POST",
        body: JSON.stringify({
          doc_type: params.docType,
          title: params.title,
          prompt: params.prompt,
          parent_policy_id: params.parentPolicyId || null,
        }),
      }
    ),
  listTemplates: () => request<{ templates: { id: string; filename: string }[] }>("/templates"),
  listWorkspaceDocuments: (workspaceId: string) => request<DocumentOut[]>(`/workspaces/${workspaceId}/documents`),
  getDocument: (id: string, includeHtml = false) =>
    request<DocumentOut>(`/documents/${id}${includeHtml ? "?include_html=true" : ""}`),
  deleteDocument: (id: string) =>
    request<{
      deleted_document_id: string;
      deleted_document_title: string;
      deleted_document_type: DocType;
      deleted_sections: number;
      deleted_references: number;
      deleted_proposed_changes: number;
      deleted_findings: number;
      deleted_versions: number;
    }>(`/documents/${id}`, { method: "DELETE" }),

  // -- analyze references --------------------------------------------------
  analyzeReferences: (workspaceId: string) =>
    request<AnalysisRunResult>(`/workspaces/${workspaceId}/analyze`, { method: "POST" }),
  listReferences: (workspaceId: string) => request<ReferenceOut[]>(`/workspaces/${workspaceId}/references`),

  // -- validate + findings --------------------------------------------------
  validate: (workspaceId: string) => request<ValidationResult>(`/workspaces/${workspaceId}/validate`, { method: "POST" }),
  listFindings: (workspaceId: string, status?: FindingStatus) =>
    request<FindingOut[]>(`/workspaces/${workspaceId}/findings${status ? `?status=${status}` : ""}`),

  // -- maintenance loop -----------------------------------------------------
  createUpdateRequest: (documentId: string, instruction: string) =>
    request<{ update_request: string; proposed_change: ProposedChangeOut }>(`/documents/${documentId}/update-requests`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),
  listProposedChanges: (workspaceId: string, status: ProposedChangeStatus | "" = "pending") =>
    request<ProposedChangeOut[]>(`/workspaces/${workspaceId}/proposed-changes?status=${status}`),
  approveProposedChange: (id: string, approved: boolean, feedback?: string) =>
    request<{ proposed_change: ProposedChangeOut; propagated: { reference_id: string; proposed_change_id: string }[] }>(
      `/proposed-changes/${id}/approve`,
      { method: "POST", body: JSON.stringify({ approved, feedback: feedback || null }) }
    ),

  // -- reports + export -----------------------------------------------------
  generateReport: (workspaceId: string) => request<ReportOut>(`/workspaces/${workspaceId}/reports`, { method: "POST" }),
  listReports: (workspaceId: string) => request<ReportOut[]>(`/workspaces/${workspaceId}/reports`),
  exportDocumentUrl: (documentId: string, fmt: string) => `${API_BASE}/export/${documentId}?fmt=${fmt}`,
  exportWorkspaceUrl: (workspaceId: string, fmt: string) => `${API_BASE}/workspaces/${workspaceId}/export?fmt=${fmt}`,

  // -- audit log --------------------------------------------------------
  listChangeEvents: (workspaceId: string) => request<ChangeEventOut[]>(`/workspaces/${workspaceId}/change-events`),
};

export const REFERENCE_STATUS_LABELS: Record<ReferenceStatus, string> = {
  valid: "Valid",
  needs_review: "Needs review",
  stale: "Stale",
  needs_reanalysis: "Needs reanalysis",
  rejected: "Rejected",
};

export const REFERENCE_STATUS_COLORS: Record<ReferenceStatus, string> = {
  valid: "#1a7f37",
  needs_review: "#b35900",
  stale: "#b35900",
  needs_reanalysis: "#b3453a",
  rejected: "#6f6a62",
};

export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.split(",")[1] || "");
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
