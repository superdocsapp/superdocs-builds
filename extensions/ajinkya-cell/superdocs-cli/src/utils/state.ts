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

const projectName = process.env.NODE_ENV === 'test' ? 'superdocs-cli-test' : 'superdocs-cli';

const configStore = new Conf<SuperDocsConfig>({
  projectName,
  configName: 'config',
  defaults: DEFAULT_CONFIG
});

const sessionStore = new Conf<DocumentSession>({
  projectName,
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

export function getConfig(): SuperDocsConfig {
  const stored = configStore.store || {};
  const apiKey = process.env.SUPERDOCS_API_KEY || stored.apiKey;
  const baseUrl = process.env.SUPERDOCS_API_URL || stored.baseUrl || DEFAULT_CONFIG.baseUrl;

  let mockMode = false;
  if (process.env.SUPERDOCS_MOCK === 'true') {
    mockMode = true;
  } else if (process.env.SUPERDOCS_MOCK === 'false') {
    mockMode = false;
  } else if (apiKey && (apiKey.startsWith('sk_') || apiKey.startsWith('sd_live'))) {
    mockMode = false;
  } else if (stored.mockMode !== undefined) {
    mockMode = Boolean(stored.mockMode);
  } else {
    mockMode = !apiKey;
  }

  return {
    ...DEFAULT_CONFIG,
    ...stored,
    apiKey,
    baseUrl,
    mockMode
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
