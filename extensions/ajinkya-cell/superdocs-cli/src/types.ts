export type ExportFormat = 'pdf' | 'docx' | 'md' | 'html' | 'txt';

export interface SuperDocsConfig {
  apiKey?: string;
  baseUrl: string;
  defaultExportFormat: ExportFormat;
  mockMode: boolean;
  agentName?: string;
}

export interface PendingVersion {
  id: string;
  content: string;
  html?: string;
  reasoning?: string;
  prompt: string;
  timestamp: string;
  additions?: number;
  deletions?: number;
}

export interface VersionHistoryItem {
  versionId: string;
  prompt: string;
  timestamp: string;
  contentPreview?: string;
}

export interface DocumentSession {
  activeDocumentId?: string;
  documentName?: string;
  originalPath?: string;
  originalContent: string;
  currentContent: string;
  originalHtml?: string;
  currentHtml?: string;
  pendingVersion?: PendingVersion;
  history: VersionHistoryItem[];
  metadata?: Record<string, unknown>;
}

export interface EditStreamChunk {
  type: 'chunk' | 'reasoning' | 'complete' | 'error';
  text?: string;
  reasoning?: string;
  versionId?: string;
  fullContent?: string;
  error?: string;
}

export interface StreamEditParams {
  documentId: string;
  prompt: string;
  currentContent?: string;
  currentHtml?: string;
  documentName?: string;
  onProgress?: (chunk: EditStreamChunk) => void;
}

export interface DocumentUploadResponse {
  document_id: string;
  name: string;
  content: string;
  html?: string;
  format?: string;
  created_at?: string;
}

export interface AgentSignupResponse {
  api_key: string;
  agent_name: string;
  message?: string;
  mcp_url?: string;
}

export interface AgentWhoamiResponse {
  agent_name: string;
  tier: string;
  documents_count: number;
  monthly_credits_remaining: number;
  valid: boolean;
}

export interface DiffResult {
  hasChanges: boolean;
  unifiedView: string;
  markdownDiff: string;
  additions: number;
  deletions: number;
  unchanged: number;
}
