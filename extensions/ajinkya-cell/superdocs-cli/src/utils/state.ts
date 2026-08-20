import Conf from 'conf';
import { SuperDocsConfig, DocumentSession } from '../types.js';

const DEFAULT_CONFIG: SuperDocsConfig = {
  baseUrl: process.env.SUPERDOCS_API_URL || 'https://api.superdocs.app/v1',
  apiKey: process.env.SUPERDOCS_API_KEY || undefined,
  defaultExportFormat: 'md',
  mockMode: process.env.SUPERDOCS_MOCK === 'true' || false,
  agentName: 'superdocs-cli-agent'
};

const DEFAULT_SESSION: DocumentSession = {
  activeDocumentId: undefined,
  documentName: undefined,
  originalPath: undefined,
  originalContent: '',
  currentContent: '',
  pendingVersion: undefined,
  history: []
};

const configStore = new Conf<SuperDocsConfig>({
  projectName: 'superdocs-cli',
  configName: 'config',
  defaults: DEFAULT_CONFIG
});

const sessionStore = new Conf<DocumentSession>({
  projectName: 'superdocs-cli',
  configName: 'session',
  defaults: DEFAULT_SESSION
});

function cleanUndefined<T extends Record<string, any>>(obj: T): T {
  const result: any = {};
  for (const [key, value] of Object.entries(obj)) {
    if (value !== undefined) {
      result[key] = value;
    }
  }
  return result;
}

// Config Methods
export function getConfig(): SuperDocsConfig {
  const stored = configStore.store || {};
  return {
    ...DEFAULT_CONFIG,
    ...stored,
    apiKey: process.env.SUPERDOCS_API_KEY || stored.apiKey,
    baseUrl: process.env.SUPERDOCS_API_URL || stored.baseUrl || DEFAULT_CONFIG.baseUrl,
    mockMode: process.env.SUPERDOCS_MOCK === 'true' || Boolean(stored.mockMode)
  };
}

export function saveConfig(updates: Partial<SuperDocsConfig>): SuperDocsConfig {
  const current = getConfig();
  const merged: any = { ...current };

  for (const [key, val] of Object.entries(updates)) {
    if (val === undefined) {
      delete merged[key];
    } else {
      merged[key] = val;
    }
  }

  configStore.clear();
  configStore.set(cleanUndefined(merged));
  return getConfig();
}

export function resetConfig(): void {
  configStore.clear();
}

// Session Methods
export function getSession(): DocumentSession {
  const stored = sessionStore.store || {};
  return {
    ...DEFAULT_SESSION,
    ...stored,
    history: stored.history || []
  };
}

export function saveSession(updates: Partial<DocumentSession>): DocumentSession {
  const current = getSession();
  const merged: any = { ...current };

  for (const [key, val] of Object.entries(updates)) {
    if (val === undefined) {
      delete merged[key];
    } else {
      merged[key] = val;
    }
  }

  sessionStore.clear();
  sessionStore.set(cleanUndefined(merged));
  return getSession();
}

export function clearSession(): void {
  sessionStore.clear();
}

export function hasActiveDocument(): boolean {
  const session = getSession();
  return Boolean(session.activeDocumentId && session.currentContent);
}
