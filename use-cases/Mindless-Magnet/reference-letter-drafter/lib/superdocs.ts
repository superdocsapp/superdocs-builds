import "server-only";
import type {
  ChatAsyncResponse,
  JobStatusResponse,
  SuperDocsTemplate,
  UploadResponse,
} from "./types";

const BASE_URL = "https://api.superdocs.app/v1";

function apiKey(): string {
  const key = process.env.SUPERDOCS_API_KEY;
  if (!key) {
    throw new Error("SUPERDOCS_API_KEY is not set. Copy .env.local.example to .env.local and add your key.");
  }
  return key;
}

function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${apiKey()}` };
}

async function assertOk(res: Response, context: string): Promise<void> {
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`SuperDocs ${context} failed: ${res.status} ${body}`);
  }
}

export async function uploadStarterDocument(sessionId: string): Promise<UploadResponse> {
  const starterHtml = "<h1>Reference Letter</h1><p>[placeholder]</p>";
  const file = new Blob([starterHtml], { type: "text/html" });
  const form = new FormData();
  form.append("file", file, "starter.html");
  form.append("session_id", sessionId);

  const res = await fetch(`${BASE_URL}/documents/upload`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  await assertOk(res, "upload");
  return res.json() as Promise<UploadResponse>;
}

export async function startDraftJob(params: {
  sessionId: string;
  message: string;
  memoryKey: string;
}): Promise<ChatAsyncResponse> {
  const res = await fetch(`${BASE_URL}/chat/async`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({
      message: params.message,
      session_id: params.sessionId,
      approval_mode: "ask_every_time",
      cross_session_memory: true,
      cross_session_memory_key: params.memoryKey,
    }),
  });
  await assertOk(res, "chat/async");
  return res.json() as Promise<ChatAsyncResponse>;
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`${BASE_URL}/jobs/${jobId}`, {
    headers: authHeaders(),
    cache: "no-store",
  });
  await assertOk(res, "job status");
  return res.json() as Promise<JobStatusResponse>;
}

export async function approveChange(params: {
  sessionId: string;
  jobId: string;
  approved: boolean;
  changes: { change_id: string; approved: boolean; feedback?: string }[];
}): Promise<{ status: string; message: string; batch_complete?: boolean }> {
  const res = await fetch(`${BASE_URL}/chat/${params.sessionId}/approve`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({
      job_id: params.jobId,
      approved: params.approved,
      changes: params.changes,
    }),
  });
  await assertOk(res, "approve");
  return res.json();
}

export async function exportDocument(params: {
  sessionId: string;
  filename: string;
}): Promise<{ blob: Blob; contentType: string; warnings: unknown[] }> {
  const res = await fetch(`${BASE_URL}/documents/export`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: params.sessionId,
      format: "docx",
      options: { filename: params.filename },
    }),
  });
  await assertOk(res, "export");

  let warnings: unknown[] = [];
  const warningsHeader = res.headers.get("X-Export-Warnings");
  if (warningsHeader) {
    warnings = JSON.parse(Buffer.from(warningsHeader, "base64").toString("utf-8"));
  }

  const blob = await res.blob();
  return {
    blob,
    contentType: res.headers.get("Content-Type") ?? "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    warnings,
  };
}

export async function listTemplates(): Promise<SuperDocsTemplate[]> {
  const res = await fetch(`${BASE_URL}/templates`, {
    headers: authHeaders(),
    cache: "no-store",
  });
  await assertOk(res, "list templates");
  const data = await res.json();
  return (data.templates ?? data) as SuperDocsTemplate[];
}

export async function uploadTemplate(file: File): Promise<SuperDocsTemplate> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`${BASE_URL}/templates/upload`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  await assertOk(res, "template upload");
  return res.json() as Promise<SuperDocsTemplate>;
}
