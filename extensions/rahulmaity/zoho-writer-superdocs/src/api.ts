import type { ApprovalPayload, SuperDocsPort } from "./types";

const API_BASE = "https://api.superdocs.app";
const CONNECTION = "superdocsapi";

export interface WriterRequest {
  url: string;
  type: "GET" | "POST";
  connectionLinkName: string;
  headers?: Record<string, string>;
  postBody?: unknown;
  responseType?: "json" | "blob";
  fileObj?: File[];
  sendAsFile?: boolean;
  data?: Record<string, string>;
}

interface SigmaWriterSdk {
  init(): Promise<void>;
  request(options: WriterRequest): Promise<unknown>;
}

declare global {
  interface Window {
    SigmaSDK?: { WRITER: SigmaWriterSdk };
  }
}

const writerSdk = (): SigmaWriterSdk => {
  const sdk = window.SigmaSDK?.WRITER;
  if (!sdk) {
    throw new Error("Sigma SDK v3 is unavailable. Open this build inside Zoho Writer.");
  }
  return sdk;
};

export type WriterRequester = (options: WriterRequest) => Promise<unknown>;

const asBlob = (response: unknown): Blob => {
  if (response instanceof Blob) return response;
  if (response instanceof ArrayBuffer) return new Blob([response]);
  if (typeof response === "object" && response !== null) {
    const data = (response as Record<string, unknown>).data;
    if (data instanceof Blob) return data;
    if (data instanceof ArrayBuffer) return new Blob([data]);
  }
  throw new Error("Export completed, but Writer returned an unsupported file response.");
};

export class SigmaSuperDocsClient implements SuperDocsPort {
  constructor(
    private readonly requester: WriterRequester = (options) =>
      writerSdk().request(options),
  ) {}

  private request(options: Omit<WriterRequest, "connectionLinkName">) {
    return this.requester({ ...options, connectionLinkName: CONNECTION });
  }

  async upload(html: string, sessionId: string): Promise<unknown> {
    const file = new File([html], "writer-selection.html", {
      type: "text/html",
    });
    return this.request({
      url: `${API_BASE}/v1/documents/upload`,
      type: "POST",
      fileObj: [file],
      sendAsFile: true,
      postBody: { session_id: sessionId, open_mode: "replace" },
      data: { index: "true" },
      responseType: "json",
    });
  }

  startChat(sessionId: string, instruction: string): Promise<unknown> {
    return this.request({
      url: `${API_BASE}/v1/chat/async`,
      type: "POST",
      headers: { "Content-Type": "application/json" },
      postBody: {
        session_id: sessionId,
        message: instruction,
        approval_mode: "ask_every_time",
        response_mode: "full",
        async_mode: true,
      },
      responseType: "json",
    });
  }

  getJob(jobId: string): Promise<unknown> {
    return this.request({
      url: `${API_BASE}/v1/jobs/${encodeURIComponent(jobId)}`,
      type: "GET",
      responseType: "json",
    });
  }

  approve(sessionId: string, payload: ApprovalPayload): Promise<unknown> {
    return this.request({
      url: `${API_BASE}/v1/chat/${encodeURIComponent(sessionId)}/approve`,
      type: "POST",
      headers: { "Content-Type": "application/json" },
      postBody: payload,
      responseType: "json",
    });
  }

  continueChat(
    sessionId: string,
    jobId: string,
    shouldContinue: boolean,
  ): Promise<unknown> {
    return this.request({
      url: `${API_BASE}/v1/chat/${encodeURIComponent(sessionId)}/continue`,
      type: "POST",
      headers: { "Content-Type": "application/json" },
      postBody: { job_id: jobId, continue: shouldContinue },
      responseType: "json",
    });
  }

  async exportDocument(sessionId: string): Promise<Blob> {
    const response = await this.request({
      url: `${API_BASE}/v1/documents/export`,
      type: "POST",
      headers: { "Content-Type": "application/json" },
      postBody: {
        session_id: sessionId,
        format: "docx",
        options: { filename: "superdocs-reviewed-selection" },
      },
      responseType: "blob",
    });
    return asBlob(response);
  }
}

export const initializeSigma = async (): Promise<void> => {
  await writerSdk().init();
};
