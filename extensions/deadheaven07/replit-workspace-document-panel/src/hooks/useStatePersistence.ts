/// <reference lib="dom" />
import { useState, useEffect, useCallback } from 'react';
import { writeArtifactToWorkspace, readProjectFile } from '../services/replit';
import { FileHashMap } from '../utils/hash';

const STATE_FILE_PATH = '.superdocs-state.json';
const LOCALSTORAGE_KEY = 'superdocs-replit-state';

export interface PersistedState {
  sessionId?: string;
  documentId?: string;
  documentType?: 'readme' | 'spec' | 'user-guide';
  selectedPaths: string[];
  fileHashes: FileHashMap;
  originalInstruction?: string;
  lastInstruction?: string;
  jobId?: string;
  jobStatus?: string;
  proposedChanges?: any;
  exportResult?: any;
  codeDeltaHash?: string;
  lastDeltaComputed?: number;
  lastUpdated: number;
  version: number;
}

const DEFAULT_STATE: PersistedState = {
  selectedPaths: [],
  fileHashes: {},
  lastUpdated: Date.now(),
  version: 1,
};

function isValidState(state: unknown): state is PersistedState {
  return (
    typeof state === 'object' &&
    state !== null &&
    'version' in state &&
    typeof (state as Record<string, unknown>).version === 'number' &&
    'selectedPaths' in state &&
    Array.isArray((state as Record<string, unknown>).selectedPaths) &&
    'fileHashes' in state &&
    typeof (state as Record<string, unknown>).fileHashes === 'object'
  );
}

async function loadFromWorkspace(): Promise<PersistedState | null> {
  try {
    const content = await readProjectFile(STATE_FILE_PATH);
    if (!content) return null;
    const parsed = JSON.parse(content);
    return isValidState(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function loadFromLocalStorage(): PersistedState | null {
  try {
    const stored = localStorage.getItem(LOCALSTORAGE_KEY);
    if (!stored) return null;
    const parsed = JSON.parse(stored);
    return isValidState(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Pure merge decision for the dual-layer persistence (localStorage +
 * `.superdocs-state.json`). The most recently updated layer wins; when only
 * one layer exists it is used as-is; when both are missing the fallback
 * (default) state is returned. Extracted as a pure function so browser
 * refresh and container re-entry behavior can be verified offline in tests.
 */
export function mergePersistedStates(
  workspace: PersistedState | null,
  local: PersistedState | null,
  fallback: PersistedState = DEFAULT_STATE
): PersistedState {
  if (workspace && local) {
    return workspace.lastUpdated >= local.lastUpdated ? workspace : local;
  }
  return workspace ?? local ?? fallback;
}

async function saveToWorkspace(state: PersistedState): Promise<void> {
  try {
    const content = JSON.stringify(state, null, 2);
    await writeArtifactToWorkspace(STATE_FILE_PATH, content);
  } catch (error) {
    console.warn('Failed to save state to workspace:', error);
  }
}

function saveToLocalStorage(state: PersistedState): void {
  try {
    localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(state));
  } catch (error) {
    console.warn('Failed to save state to localStorage:', error);
  }
}

export function useStatePersistence(): readonly [
  PersistedState,
  (partial: Partial<PersistedState>) => Promise<void>,
  () => Promise<void>,
  {
    updateSession: (session: { sessionId?: string; documentId?: string; documentType?: 'readme' | 'spec' | 'user-guide' }) => Promise<void>;
    updateJobState: (job: { jobId?: string; jobStatus?: string; proposedChanges?: any }) => Promise<void>;
    updateExportState: (exportState: { exportResult?: any }) => Promise<void>;
    updateCodeDelta: (delta: { codeDeltaHash?: string; lastDeltaComputed?: number }) => Promise<void>;
    updateFileSelection: (paths: string[]) => Promise<void>;
    updateFileHashes: (hashes: FileHashMap) => Promise<void>;
    updateInstruction: (instruction: { originalInstruction?: string; lastInstruction?: string }) => Promise<void>;
  }
] {
  const [state, setState] = useState<PersistedState>(DEFAULT_STATE);

  useEffect(() => {
    let mounted = true;

    async function load() {
      const workspaceState = await loadFromWorkspace();
      const localState = loadFromLocalStorage();

      const mergedState = mergePersistedStates(workspaceState, localState);

      if (mounted) {
        setState(mergedState);
      }
    }

    load();

    return () => {
      mounted = false;
    };
  }, []);

  const updateState = useCallback(async (partial: Partial<PersistedState>): Promise<void> => {
    setState(prev => {
      const newState = {
        ...prev,
        ...partial,
        lastUpdated: Date.now(),
      };
      saveToLocalStorage(newState);
      saveToWorkspace(newState).catch(console.warn);
      return newState;
    });
  }, []);

  const clearState = useCallback(async (): Promise<void> => {
    const cleared = { ...DEFAULT_STATE, lastUpdated: Date.now() };
    setState(cleared);
    saveToLocalStorage(cleared);
    await saveToWorkspace(cleared);
  }, []);

  const helpers = {
    updateSession: async (session: { sessionId?: string; documentId?: string; documentType?: 'readme' | 'spec' | 'user-guide' }) => 
      updateState({ sessionId: session.sessionId, documentId: session.documentId, documentType: session.documentType }),
    updateJobState: async (job: { jobId?: string; jobStatus?: string; proposedChanges?: any }) =>
      updateState({ jobId: job.jobId, jobStatus: job.jobStatus, proposedChanges: job.proposedChanges }),
    updateExportState: async (exportState: { exportResult?: any }) =>
      updateState({ exportResult: exportState.exportResult }),
    updateCodeDelta: async (delta: { codeDeltaHash?: string; lastDeltaComputed?: number }) =>
      updateState({ codeDeltaHash: delta.codeDeltaHash, lastDeltaComputed: delta.lastDeltaComputed }),
    updateFileSelection: async (paths: string[]) =>
      updateState({ selectedPaths: paths }),
    updateFileHashes: async (hashes: FileHashMap) =>
      updateState({ fileHashes: hashes }),
    updateInstruction: async (instruction: { originalInstruction?: string; lastInstruction?: string }) =>
      updateState({ originalInstruction: instruction.originalInstruction, lastInstruction: instruction.lastInstruction }),
  };

  return [state, updateState, clearState, helpers] as const;
}

export function usePersistedFileHashes() {
  const [state, , , helpers] = useStatePersistence();
  return {
    fileHashes: state.fileHashes,
    setFileHashes: helpers.updateFileHashes,
  };
}