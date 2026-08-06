import axios from "axios";

import type {
  BriefResponse,
  BriefStatusResponse,
  DocumentUploadResponse,
} from "@/types/brief";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 120_000,
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail =
      error?.response?.data?.detail ||
      error?.message ||
      "Request failed";
    return Promise.reject(new Error(typeof detail === "string" ? detail : JSON.stringify(detail)));
  },
);

export async function uploadDocuments(form: FormData): Promise<DocumentUploadResponse> {
  const { data } = await api.post<DocumentUploadResponse>("/documents/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function createBrief(sessionId: string): Promise<BriefStatusResponse> {
  const { data } = await api.post<BriefStatusResponse>("/briefs", {
    session_id: sessionId,
  });
  return data;
}

export async function getBrief(briefId: string): Promise<BriefResponse> {
  const { data } = await api.get<BriefResponse>(`/briefs/${briefId}`);
  return data;
}

export async function getBriefStatus(briefId: string): Promise<BriefStatusResponse> {
  const { data } = await api.get<BriefStatusResponse>(`/briefs/${briefId}/status`);
  return data;
}

export async function checkHealth(): Promise<{ status: string }> {
  const { data } = await api.get<{ status: string }>("/health");
  return data;
}

export type ReportExportFormat = "pdf" | "docx" | "markdown" | "html" | "json";

export async function exportBriefReport(
  briefId: string,
  format: ReportExportFormat,
): Promise<{ blob: Blob; filename: string }> {
  const response = await api.get(`/reports/${briefId}/export`, {
    params: { format },
    responseType: "blob",
  });
  const disposition = response.headers["content-disposition"] as string | undefined;
  const match = disposition?.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || `interview-report.${format === "markdown" ? "md" : format}`;
  return { blob: response.data as Blob, filename };
}

export type SuperDocsPendingChange = {
  change_id?: string;
  operation?: string;
  ai_explanation?: string;
  chunk_id?: string;
  [key: string]: unknown;
};

export type SuperDocsStartResponse = {
  brief_id: string;
  session_id: string;
  job_id: string;
  status: string;
  approval_mode: string;
  upload: Record<string, unknown>;
  message: string;
};

export type SuperDocsJobStatus = {
  job_id: string;
  status: string;
  pending_changes: SuperDocsPendingChange[];
  pending_count: number;
  ai_response?: string | null;
};

export async function getSuperDocsHealth(): Promise<{
  enabled: boolean;
  configured: boolean;
  base_url: string;
  message: string;
}> {
  const { data } = await api.get("/superdocs/health");
  return data;
}

export async function startSuperDocsPolish(
  briefId: string,
  body?: { instruction?: string; approval_mode?: string },
): Promise<SuperDocsStartResponse> {
  const { data } = await api.post<SuperDocsStartResponse>(
    `/superdocs/briefs/${briefId}/start`,
    body ?? {},
    { timeout: 180_000 },
  );
  return data;
}

export async function getSuperDocsJob(jobId: string): Promise<SuperDocsJobStatus> {
  const { data } = await api.get<SuperDocsJobStatus>(`/superdocs/jobs/${jobId}`, {
    timeout: 60_000,
  });
  return data;
}

export async function approveSuperDocsChanges(
  sessionId: string,
  payload: {
    job_id: string;
    approved: boolean;
    changes?: { change_id: string; approved: boolean; feedback?: string }[];
    feedback?: string;
  },
): Promise<{ message: string }> {
  const { data } = await api.post(`/superdocs/sessions/${sessionId}/approve`, payload, {
    timeout: 60_000,
  });
  return data;
}

export async function exportSuperDocsSession(
  sessionId: string,
  format: "docx" | "pdf" | "html" | "markdown" | "txt" = "docx",
): Promise<{ blob: Blob; filename: string }> {
  const response = await api.post(
    `/superdocs/sessions/${sessionId}/export`,
    null,
    {
      params: { format, filename: "interview-preparation-brief" },
      responseType: "blob",
      timeout: 180_000,
    },
  );
  const disposition = response.headers["content-disposition"] as string | undefined;
  const match = disposition?.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || `interview-preparation-brief.${format === "markdown" ? "md" : format}`;
  return { blob: response.data as Blob, filename };
}
