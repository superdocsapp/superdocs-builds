export type Author = { id: string; name: string };

export type DeclareFacts = {
  authors: Author[];
  contributions: Array<{ authorId: string; evidence: string; roleIds: string[]; status: "approved" | "ambiguous" }>;
  funding: { status: "reported" | "none" | "unknown"; funder?: string; awardNumber?: string; evidence: string };
  conflicts: { status: "reported" | "none" | "unknown"; items: Array<{ authorId?: string; disclosure?: string; evidence: string }> };
};

export type Analysis = {
  contributions: Array<{ authorId: string; evidence: string; roleIds: string[]; status: "proposed" | "ambiguous" | "unsupported" }>;
  funding: DeclareFacts["funding"];
  conflicts: DeclareFacts["conflicts"];
  issues: Array<{ type: string; message: string; authorId?: string; roleId?: string }>;
};

const apiUrl = process.env.NEXT_PUBLIC_DECLARE_API_URL ?? "http://localhost:8000/api";

const request = async <T>(path: string, body?: unknown): Promise<T> => {
  const response = await fetch(`${apiUrl}${path}`, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const result = await response.json().catch(() => null) as { data?: T; error?: string; message?: string } | null;

  if (!response.ok || !result?.data) {
    throw new Error(result?.error ?? result?.message ?? "The Declare server did not return a valid response.");
  }

  return result.data;
};

export const analyzeDeclaration = (input: { authors: Author[]; contributions: string; funding: string; conflicts: string }) =>
  request<Analysis>("/declare/analyze", input);

export const createStatements = (facts: DeclareFacts) => request<{
  contributionStatement: string;
  fundingStatement: string;
  conflictStatement: string;
}>("/declare/statements", facts);

export const uploadManuscript = (input: { sessionId: string; filename: string; fileBase64: string }) =>
  request<{ html?: string; document_html?: string }>("/superdocs/upload", { ...input, returnHtml: true });

export const applyStatements = (input: { sessionId: string; facts: DeclareFacts }) =>
  request<{ job_id: string; session_id: string; status: string }>("/superdocs/apply", { ...input, approvalMode: "approve_all" });

export const getSuperdocsJob = (jobId: string) => request<Record<string, unknown>>(`/superdocs/jobs/${jobId}`);

export const decideSuperdocsChanges = (input: { sessionId: string; jobId: string; approved: boolean; changes?: Array<{ changeId: string; approved: boolean }> }) =>
  request<unknown>("/superdocs/approve", input);

export const exportManuscript = async (sessionId: string) => {
  const response = await fetch(`${apiUrl}/superdocs/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId, format: "docx" }),
  });

  if (!response.ok) {
    throw new Error("Unable to export the manuscript.");
  }

  return response.blob();
};
