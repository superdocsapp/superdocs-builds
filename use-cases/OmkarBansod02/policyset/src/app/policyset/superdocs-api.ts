import type { ChangeSet, PolicyDocumentType, PolicyProfile } from "@/domain";
import type {
  SuperDocsJobView,
  PolicyDocumentExportFormat,
  SuperDocsReviewView,
  SuperDocsSessionDocumentView,
  SuperDocsSynchronizedStartView,
  SuperDocsWorkspaceSession,
} from "./superdocs-contract";

const API_ROOT = "/api/policyset/superdocs";

export async function initializeSuperDocsSession(
  profile: PolicyProfile,
  signal?: AbortSignal,
): Promise<SuperDocsWorkspaceSession> {
  return requestJson(`${API_ROOT}/session`, {
    method: "POST",
    body: JSON.stringify({ profile }),
    signal,
  });
}

export async function startSuperDocsEdit(
  input: {
    sessionId: string;
    documentId: string;
    instruction: string;
  },
  signal?: AbortSignal,
): Promise<SuperDocsJobView> {
  return requestJson(`${API_ROOT}/edit`, {
    method: "POST",
    body: JSON.stringify(input),
    signal,
  });
}

export async function getSuperDocsJob(
  input: { jobId: string; sessionId: string; documentId: string },
  signal?: AbortSignal,
): Promise<SuperDocsJobView> {
  const search = new URLSearchParams({
    sessionId: input.sessionId,
    documentId: input.documentId,
  });
  return requestJson(
    `${API_ROOT}/jobs/${encodeURIComponent(input.jobId)}?${search}`,
    { signal, cache: "no-store" },
  );
}

export async function submitSuperDocsReview(
  input: {
    jobId: string;
    sessionId: string;
    documentId: string;
    approved: boolean;
  },
  signal?: AbortSignal,
): Promise<SuperDocsReviewView> {
  return requestJson(`${API_ROOT}/review`, {
    method: "POST",
    body: JSON.stringify(input),
    signal,
  });
}

export async function refreshSuperDocsDocuments(
  sessionId: string,
  signal?: AbortSignal,
): Promise<readonly SuperDocsSessionDocumentView[]> {
  const search = new URLSearchParams({ sessionId });
  const response = await requestJson<{
    documents: readonly SuperDocsSessionDocumentView[];
  }>(`${API_ROOT}/session?${search}`, { signal, cache: "no-store" });
  return response.documents;
}

export async function exportSuperDocsDocument(
  input: {
    sessionId: string;
    documentType: PolicyDocumentType;
    documentId: string;
    documentIds: Record<PolicyDocumentType, string>;
    format: PolicyDocumentExportFormat;
    companyName: string;
  },
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string; warningCount: number }> {
  const response = await fetch(`${API_ROOT}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal,
    cache: "no-store",
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const message =
      isRecord(payload) && typeof payload.error === "string"
        ? payload.error
        : "The selected policy could not be exported.";
    throw new Error(message);
  }

  const blob = await response.blob();
  if (blob.size === 0) {
    throw new Error("SuperDocs returned an empty export.");
  }
  return {
    blob,
    filename: responseFilename(response.headers.get("Content-Disposition"), input),
    warningCount: Number(
      response.headers.get("X-SuperDocs-Export-Warning-Count") ?? "0",
    ),
  };
}

export async function startSuperDocsSynchronizedChange(
  input: {
    sessionId: string;
    documentIds: Record<PolicyDocumentType, string>;
    changeSet: ChangeSet;
  },
  signal?: AbortSignal,
): Promise<SuperDocsSynchronizedStartView> {
  return requestJson(`${API_ROOT}/synchronized`, {
    method: "POST",
    body: JSON.stringify(input),
    signal,
  });
}

export async function getSuperDocsSynchronizedJob(
  input: {
    jobId: string;
    sessionId: string;
    documentType: PolicyDocumentType;
    documentIds: Record<PolicyDocumentType, string>;
    changeSet: ChangeSet;
  },
  signal?: AbortSignal,
): Promise<SuperDocsJobView> {
  return requestJson(
    `${API_ROOT}/synchronized/jobs/${encodeURIComponent(input.jobId)}`,
    {
      method: "POST",
      body: JSON.stringify(input),
      signal,
      cache: "no-store",
    },
  );
}

export async function submitSuperDocsSynchronizedReview(
  input: {
    jobId: string;
    sessionId: string;
    documentType: PolicyDocumentType;
    documentIds: Record<PolicyDocumentType, string>;
    changeSet: ChangeSet;
    approved: boolean;
  },
  signal?: AbortSignal,
): Promise<SuperDocsReviewView> {
  return requestJson(`${API_ROOT}/synchronized/review`, {
    method: "POST",
    body: JSON.stringify(input),
    signal,
  });
}

async function requestJson<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(url, { ...init, headers });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      isRecord(payload) && typeof payload.error === "string"
        ? payload.error
        : "The SuperDocs request failed.";
    throw new Error(message);
  }
  return payload as T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function responseFilename(
  contentDisposition: string | null,
  input: { documentType: PolicyDocumentType; format: PolicyDocumentExportFormat },
): string {
  const matched = contentDisposition?.match(/filename="([^"]+)"/i)?.[1];
  const safe = matched?.split(/[\\/]/).pop();
  return safe || `policyset-${input.documentType}.${input.format}`;
}
