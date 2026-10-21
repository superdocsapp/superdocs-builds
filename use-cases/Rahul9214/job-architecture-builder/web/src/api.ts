import type {
  ArchitectureSummary,
  CorpusSummary,
  ExceptionCard,
  FrameworkPayload,
  ImpactPayload,
  ProfileDetail,
  ProfileSummary,
  ReviewPayload,
  RoleDetail,
  SuperDocsStatus,
  UpdatePlanView,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  const payload = (await response.json()) as T | { ok: false; code?: string; message?: string };
  if (!response.ok) {
    const error = payload as { code?: string; message?: string };
    throw new ApiError(response.status, error.code ?? "error", error.message ?? "Request failed");
  }
  return payload as T;
}

export const api = {
  corpora: () => request<{ corpora: CorpusSummary[] }>("/api/corpora"),
  corpus: (id: string) => request<CorpusSummary>(`/api/corpora/${id}`),
  analyze: (id: string) =>
    request<ArchitectureSummary>(`/api/corpora/${id}/analyze`, { method: "POST" }),
  architecture: (id: string) => request<ArchitectureSummary>(`/api/architecture/${id}`),
  role: (id: string, roleId: string) => request<RoleDetail>(`/api/architecture/${id}/roles/${roleId}`),
  exceptions: (id: string) =>
    request<{ provisional: ExceptionCard[]; hybrid_bridge: ExceptionCard[]; misfit: ExceptionCard[] }>(
      `/api/exceptions/${id}`,
    ),
  framework: (id: string) => request<FrameworkPayload>(`/api/framework/${id}`),
  profiles: (id: string) =>
    request<{ profiles: ProfileSummary[]; review_artifacts: ProfileDetail[] }>(`/api/profiles/${id}`),
  profile: (id: string, profileId: string) => request<ProfileDetail>(`/api/profiles/${id}/${profileId}`),
  impact: (id: string, body: Record<string, string>) =>
    request<ImpactPayload>(`/api/impact/${id}/level-change`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  plan: (id: string, body: Record<string, string>) =>
    request<{ impact: ImpactPayload; plans: UpdatePlanView[]; review: ReviewPayload }>(
      `/api/updates/${id}/plan`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  review: (id: string) => request<ReviewPayload>(`/api/review/${id}`),
  decisions: (id: string, items: Array<{ plan_id: string; approved: boolean }>) =>
    request<ReviewPayload>(`/api/review/${id}/decisions`, {
      method: "POST",
      body: JSON.stringify({ items }),
    }),
  apply: (id: string) => request<ReviewPayload>(`/api/review/${id}/apply`, { method: "POST" }),
  exportLocal: (id: string, kind: string, profileId?: string) =>
    request<{ ok: boolean; path: string; filename: string; via: string; superdocs: boolean }>(
      `/api/export/${id}`,
      { method: "POST", body: JSON.stringify({ kind, profile_id: profileId }) },
    ),
  superdocs: () => request<SuperDocsStatus>("/api/superdocs/status"),
};
