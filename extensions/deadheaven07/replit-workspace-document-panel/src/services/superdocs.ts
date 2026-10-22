import {
  SuperDocsConfig,
  DocumentUploadResult,
  JobStatus,
  ExportResult,
  ChatAsyncRequest,
  ApproveChangesRequest,
  ContinueJobRequest,
  ExportDocumentRequest,
  SessionInitRequest,
  SyncHtmlRequest,
  SyncHtmlResponse,
  DocumentVersion,
  GetVersionsResponse,
  GetTemplatesResponse,
  Prompt,
  GetPromptsResponse,
} from '../types/superdocs';

const DEFAULT_BASE_URL = 'https://api.superdocs.app';
const POLL_INTERVAL_MS = 3000;
const MAX_POLLS = 200;
const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_RETRY_DELAY_MS = 1000;

export interface RetryConfig {
  maxRetries?: number;
  retryDelayMs?: number;
}

export interface SuperDocsClientConfig extends SuperDocsConfig {
  retryConfig?: RetryConfig;
}

function isRetriableError(error: Error): boolean {
  const message = error.message.toLowerCase();
  return (
    message.includes('network') ||
    message.includes('fetch') ||
    message.includes('timeout') ||
    message.includes('econnreset') ||
    message.includes('etimedout') ||
    message.includes('502') ||
    message.includes('503') ||
    message.includes('504')
  );
}

async function withRetry<T>(
  fn: () => Promise<T>,
  retries: number,
  delay: number,
  signal?: AbortSignal
): Promise<T> {
  try {
    return await fn();
  } catch (error) {
    if (signal?.aborted) {
      const abortError = new Error('Aborted');
      abortError.name = 'AbortError';
      throw abortError;
    }
    if (retries > 0 && error instanceof Error && isRetriableError(error)) {
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(resolve, delay);
        signal?.addEventListener('abort', () => {
          clearTimeout(timeout);
          const abortError = new Error('Aborted');
          abortError.name = 'AbortError';
          reject(abortError);
        });
      });
      return withRetry(fn, retries - 1, delay * 2, signal);
    }
    throw error;
  }
}

function getMaxRetries(config: RetryConfig | undefined): number {
  return config?.maxRetries ?? DEFAULT_MAX_RETRIES;
}

function getRetryDelayMs(config: RetryConfig | undefined): number {
  return config?.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
}

export class SuperDocsClient {
  private baseUrl: string;
  private apiKey: string;
  private retryConfig: RetryConfig | undefined;

  constructor(config: SuperDocsClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
    this.apiKey = config.apiKey;
    this.retryConfig = config.retryConfig;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {},
    retryable = false,
    signal?: AbortSignal
  ): Promise<T> {
    const maxRetries = retryable ? getMaxRetries(this.retryConfig) : 0;
    const delay = getRetryDelayMs(this.retryConfig);

    return withRetry(async () => {
      const response = await fetch(`${this.baseUrl}${endpoint}`, {
        ...options,
        signal,
        headers: {
          'Authorization': `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json',
          ...options.headers,
        },
      });

      if (!response.ok) {
        const errorText = await response.text();
        const error = new Error(`SuperDocs API error (${response.status}): ${errorText}`);
        (error as Error & { status?: number }).status = response.status;
        throw error;
      }

      return response.json();
    }, maxRetries, delay, signal);
  }

  async initSession(sessionId?: string, signal?: AbortSignal): Promise<string> {
    const payload: SessionInitRequest = sessionId ? { session_id: sessionId } : {};
    const response = await this.request<{ session_id: string }>(
      '/v1/sessions/init',
      { method: 'POST', body: JSON.stringify(payload) },
      true,
      signal
    );
    return response.session_id;
  }

  async uploadDocument(
    filename: string,
    content: string,
    sessionId?: string,
    returnHtml = true,
    signal?: AbortSignal
  ): Promise<DocumentUploadResult> {
    const session_id = sessionId || (await this.initSession(undefined, signal));
    const file_base64 = btoa(content);

    const payload = {
      filename,
      file_base64,
      return_html: returnHtml,
      session_id,
    };

    const response = await this.request<DocumentUploadResult>(
      '/v1/documents/upload-base64',
      { method: 'POST', body: JSON.stringify(payload) },
      false,
      signal
    );

    return {
      session_id: response.session_id || session_id,
      document_id: response.document_id || response.focused_document_id || 'doc_primary',
      chunks_count: response.chunks_count ?? 0,
      version_id: response.version_id ?? '',
      page_setup: response.page_setup ?? {},
      html: response.html,
    };
  }

  async chatAsync(request: ChatAsyncRequest, signal?: AbortSignal): Promise<string> {
    const response = await this.request<{ job_id: string }>(
      '/v1/chat/async',
      { method: 'POST', body: JSON.stringify(request) },
      false,
      signal
    );
    return response.job_id;
  }

  async pollJob(jobId: string, signal?: AbortSignal): Promise<JobStatus> {
    return this.request<JobStatus>(`/v1/jobs/${jobId}`, {}, true, signal);
  }

  async waitForJob(
    jobId: string,
    onProgress?: (status: JobStatus) => void,
    signal?: AbortSignal
  ): Promise<JobStatus> {
    let polls = 0;

    while (polls < MAX_POLLS) {
      const status = await this.pollJob(jobId, signal);

      if (onProgress) {
        onProgress(status);
      }

      if (status.status === 'completed' || status.status === 'failed' || status.status === 'awaiting_approval') {
        return status;
      }

      await new Promise((resolve, reject) => {
        const timeout = setTimeout(resolve, POLL_INTERVAL_MS);
        signal?.addEventListener('abort', () => {
          clearTimeout(timeout);
          const abortError = new Error('Aborted');
          abortError.name = 'AbortError';
          reject(abortError);
        });
      });
      polls++;
    }

    throw new Error(`Job ${jobId} timed out after ${MAX_POLLS * POLL_INTERVAL_MS / 1000} seconds`);
  }

  async approveChanges(request: ApproveChangesRequest, signal?: AbortSignal): Promise<JobStatus> {
    const { session_id, ...payload } = request;
    return this.request<JobStatus>(
      `/v1/chat/${session_id}/approve`,
      { method: 'POST', body: JSON.stringify(payload) },
      false,
      signal
    );
  }

  async continueJob(request: ContinueJobRequest, sessionId: string, signal?: AbortSignal): Promise<JobStatus> {
    return this.request<JobStatus>(
      `/v1/chat/${sessionId}/continue`,
      { method: 'POST', body: JSON.stringify(request) },
      false,
      signal
    );
  }

  async exportDocument(request: ExportDocumentRequest, signal?: AbortSignal): Promise<ExportResult> {
    return this.request<ExportResult>(
      '/v1/documents/export',
      { method: 'POST', body: JSON.stringify(request) },
      false,
      signal
    );
  }

  async downloadExport(downloadUrl: string, signal?: AbortSignal): Promise<Blob> {
    const response = await fetch(downloadUrl, {
      signal,
      headers: {
        'Authorization': `Bearer ${this.apiKey}`,
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to download export: ${response.status}`);
    }

    return response.blob();
  }

  async syncHtml(request: SyncHtmlRequest, signal?: AbortSignal): Promise<SyncHtmlResponse> {
    return this.request<SyncHtmlResponse>(
      '/v1/documents/sync-html',
      { method: 'POST', body: JSON.stringify(request) },
      false,
      signal
    );
  }

  async getVersions(documentId: string, signal?: AbortSignal): Promise<GetVersionsResponse> {
    return this.request<GetVersionsResponse>(
      `/v1/documents/${documentId}/versions`,
      {},
      true,
      signal
    );
  }

  async getDocumentVersion(documentId: string, versionId: string, signal?: AbortSignal): Promise<DocumentVersion> {
    return this.request<DocumentVersion>(
      `/v1/documents/${documentId}/versions/${versionId}`,
      {},
      true,
      signal
    );
  }

  async revertToVersion(documentId: string, versionId: string, signal?: AbortSignal): Promise<JobStatus> {
    return this.request<JobStatus>(
      `/v1/documents/${documentId}/versions/${versionId}/revert`,
      { method: 'POST' },
      false,
      signal
    );
  }

  async getTemplates(signal?: AbortSignal): Promise<GetTemplatesResponse> {
    return this.request<GetTemplatesResponse>('/v1/templates', {}, true, signal);
  }

  async getPrompts(signal?: AbortSignal): Promise<GetPromptsResponse> {
    return this.request<GetPromptsResponse>('/v1/prompts', {}, true, signal);
  }

  async getPrompt(promptId: string, signal?: AbortSignal): Promise<Prompt> {
    return this.request<Prompt>(`/v1/prompts/${promptId}`, {}, true, signal);
  }
}

export function createSuperDocsClient(apiKey: string, baseUrl = DEFAULT_BASE_URL, retryConfig?: RetryConfig): SuperDocsClient {
  return new SuperDocsClient({ baseUrl, apiKey, retryConfig });
}