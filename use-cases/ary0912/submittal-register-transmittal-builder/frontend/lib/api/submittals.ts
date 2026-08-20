import { get, patch, post } from "./client";
import type {
  HealthResponse,
  OverdueRegisterResponse,
  RegisterItem,
  RegisterResponse,
  RegisterStatus,
  ReviewFindingRequest,
  ReviewFindingResponse,
  RunWorkflowResponse,
  SubmittalDetail,
} from "./types";

// ============================================================
// Health
// ============================================================

export function getHealth(): Promise<HealthResponse> {
  return get<HealthResponse>("/health");
}

// ============================================================
// Register
// ============================================================

export function getProjectSubmittals(
  projectId: string,
): Promise<RegisterResponse> {
  return get<RegisterResponse>(`/projects/${projectId}/submittals`);
}

export function getOverdueSubmittals(
  projectId: string,
): Promise<OverdueRegisterResponse> {
  return get<OverdueRegisterResponse>(
    `/projects/${projectId}/submittals/overdue`,
  );
}

export function getSubmittalDetail(
  submittalNumber: string,
): Promise<SubmittalDetail> {
  return get<SubmittalDetail>(`/submittals/${submittalNumber}`);
}

export function updateRegisterStatus(
  submittalNumber: string,
  status: RegisterStatus,
): Promise<RegisterItem> {
  return patch<RegisterItem>(
    `/submittals/${encodeURIComponent(submittalNumber)}/register-status`,
    { status },
  );
}

// ============================================================
// Findings / Review
// ============================================================

export function reviewFinding(
  findingId: string,
  payload: ReviewFindingRequest,
): Promise<ReviewFindingResponse> {
  return post<ReviewFindingResponse>(
    `/findings/${findingId}/review`,
    payload,
  );
}

// ============================================================
// Workflow Run
// ============================================================

export interface RunWorkflowPayload {
  project_id?: string;
  submittal_number?: string;
  specification_section?: string;
}

export function runWorkflow(
  payload: RunWorkflowPayload = {},
): Promise<RunWorkflowResponse> {
  return post<RunWorkflowResponse>("/runs/submittal", payload);
}

// ============================================================
// Seed Demo
// ============================================================

export interface SeedDemoResponse {
  status: string;
  project_id: string;
  items_count: number;
  items: RegisterItem[];
}

export function seedDemo(
  projectId: string,
): Promise<SeedDemoResponse> {
  return post<SeedDemoResponse>(
    `/projects/${projectId}/seed-demo`,
  );
}
