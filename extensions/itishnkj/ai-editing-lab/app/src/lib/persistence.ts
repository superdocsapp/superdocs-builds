/**
 * Persistence providers for the lab workspace.
 *
 * One interface, two implementations:
 * - Guest: the pre-auth localStorage behavior, same keys, unchanged format.
 * - Authenticated: server-side per-user storage with debounced saves and
 *   save-status reporting.
 *
 * The authenticated provider never reads or writes the guest localStorage
 * keys, so signing in or out never destroys local guest work (and the door
 * stays open for a future import/merge flow).
 */

export type WorkspaceSaveStatus = 'local' | 'saving' | 'saved' | 'error';

/** Minimal structural view of the lab state used by persistence providers. */
export type PersistableLabState = {
  documentSession: { persistence: string };
} & Record<string, unknown>;

export interface GuestPersistence {
  mode: 'guest';
  /** Raw parsed snapshot from localStorage, or null when absent/corrupt. */
  loadSync(): unknown;
  persist(state: PersistableLabState): void;
}

export interface AuthenticatedPersistence {
  mode: 'authenticated';
  /** Raw workspace snapshot from the server, or null for a new account. */
  load(): Promise<unknown>;
  persist(state: PersistableLabState): void;
  /** Force any queued save to complete (used before sign-out). */
  flush(): Promise<void>;
  onStatusChange(listener: (status: WorkspaceSaveStatus) => void): () => void;
  dispose(): void;
}

export type LabPersistence = GuestPersistence | AuthenticatedPersistence;

export const GUEST_STATE_STORAGE_KEY = 'ai-editing-lab-state-v4';
const LEGACY_GUEST_STATE_STORAGE_KEY = 'ai-editing-lab-state-v2';
const GUEST_SESSION_FLAG_KEY = 'ai-editing-lab-guest-session-entered-v1';

export function createGuestPersistence(): GuestPersistence {
  return {
    mode: 'guest',
    loadSync() {
      try {
        const stored =
          localStorage.getItem(GUEST_STATE_STORAGE_KEY) ??
          localStorage.getItem(LEGACY_GUEST_STATE_STORAGE_KEY);
        return stored ? (JSON.parse(stored) as unknown) : null;
      } catch {
        localStorage.removeItem(GUEST_STATE_STORAGE_KEY);
        return null;
      }
    },
    persist(state) {
      try {
        if (state.documentSession.persistence === 'session-only') {
          localStorage.removeItem(GUEST_STATE_STORAGE_KEY);
          return;
        }
        localStorage.setItem(GUEST_STATE_STORAGE_KEY, JSON.stringify(state));
      } catch {
        // Storage may be full or unavailable; guest state stays in memory.
      }
    },
  };
}

const API_ROOT = `${import.meta.env.BASE_URL}api`;
const WORKSPACE_ENDPOINT = `${API_ROOT}/user/workspace`;
const PREFERENCES_ENDPOINT = `${API_ROOT}/user/preferences`;

const SAVE_DEBOUNCE_MS = 900;
const SAVE_RETRY_MS = 8000;

export function createAuthenticatedPersistence(): AuthenticatedPersistence {
  let queued: PersistableLabState | null = null;
  let inFlight: Promise<void> | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;
  let status: WorkspaceSaveStatus = 'saved';
  const listeners = new Set<(next: WorkspaceSaveStatus) => void>();

  const setStatus = (next: WorkspaceSaveStatus) => {
    if (status === next) return;
    status = next;
    for (const listener of listeners) listener(next);
  };

  const clearTimer = () => {
    if (timer != null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  const schedule = (delayMs: number) => {
    if (disposed) return;
    clearTimer();
    timer = setTimeout(() => {
      timer = null;
      void runSave();
    }, delayMs);
  };

  const saveSnapshot = async (snapshot: PersistableLabState): Promise<void> => {
    // Session-only documents are never persisted (mirrors guest behavior,
    // which removes the localStorage snapshot), so clear the stored
    // workspace instead of uploading it.
    const sessionOnly = snapshot.documentSession.persistence === 'session-only';
    const response = sessionOnly
      ? await fetch(WORKSPACE_ENDPOINT, {
          method: 'DELETE',
          credentials: 'same-origin',
        })
      : await fetch(WORKSPACE_ENDPOINT, {
          method: 'PUT',
          credentials: 'same-origin',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(snapshot),
        });
    if (!response.ok) {
      throw new Error(`Workspace save failed (${response.status})`);
    }
  };

  const runSave = async (): Promise<void> => {
    if (disposed || queued == null || inFlight != null) return;
    const snapshot = queued;
    queued = null;
    setStatus('saving');
    inFlight = (async () => {
      try {
        await saveSnapshot(snapshot);
        if (queued == null) setStatus('saved');
      } catch {
        // Keep the newest unsaved snapshot around and retry later.
        if (queued == null) queued = snapshot;
        setStatus('error');
        schedule(SAVE_RETRY_MS);
      }
    })();
    await inFlight;
    inFlight = null;
    if (queued != null && timer == null && !disposed) {
      // A newer change arrived while saving; save it promptly.
      schedule(50);
    }
  };

  return {
    mode: 'authenticated',
    async load() {
      const response = await fetch(WORKSPACE_ENDPOINT, {
        credentials: 'same-origin',
        headers: { accept: 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`Workspace load failed (${response.status})`);
      }
      const data = (await response.json()) as { workspace?: unknown };
      return data?.workspace ?? null;
    },
    persist(state) {
      if (disposed) return;
      queued = state;
      setStatus('saving');
      schedule(SAVE_DEBOUNCE_MS);
    },
    async flush() {
      // Drain the queue, but give up after a couple of failed attempts so
      // sign-out is never blocked indefinitely.
      for (let attempt = 0; attempt < 2 && !disposed; attempt += 1) {
        if (inFlight) await inFlight;
        if (queued == null) break;
        clearTimer();
        await runSave();
      }
      if (inFlight) await inFlight;
    },
    onStatusChange(listener) {
      listeners.add(listener);
      listener(status);
      return () => {
        listeners.delete(listener);
      };
    },
    dispose() {
      disposed = true;
      clearTimer();
      listeners.clear();
    },
  };
}

export interface AuthenticatedPreferencesPersistence {
  load(): Promise<Record<string, unknown> | null>;
  persist(preferences: Record<string, unknown>): void;
}

const PREFERENCES_DEBOUNCE_MS = 500;
const PREFERENCES_RETRY_MS = 4000;

export function createAuthenticatedPreferencesPersistence(): AuthenticatedPreferencesPersistence {
  let queued: Record<string, unknown> | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let saving = false;

  const schedule = (delayMs: number) => {
    if (timer != null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void save();
    }, delayMs);
  };

  const save = async () => {
    if (saving || queued == null) return;
    const snapshot = queued;
    queued = null;
    saving = true;
    try {
      const response = await fetch(PREFERENCES_ENDPOINT, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(snapshot),
      });
      if (!response.ok) {
        throw new Error(`Preferences save failed (${response.status})`);
      }
    } catch {
      if (queued == null) queued = snapshot;
      schedule(PREFERENCES_RETRY_MS);
    } finally {
      saving = false;
      if (queued != null && timer == null) schedule(50);
    }
  };

  return {
    async load() {
      const response = await fetch(PREFERENCES_ENDPOINT, {
        credentials: 'same-origin',
        headers: { accept: 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`Preferences load failed (${response.status})`);
      }
      const data = (await response.json()) as { preferences?: unknown };
      return data.preferences && typeof data.preferences === 'object'
        ? (data.preferences as Record<string, unknown>)
        : null;
    },
    persist(preferences) {
      queued = preferences;
      schedule(PREFERENCES_DEBOUNCE_MS);
    },
  };
}

/**
 * Welcome-screen routing helpers.
 *
 * "Entered" means the visitor explicitly chose "Try the demo" (or predates
 * the welcome screen and already has a guest snapshot). The flag is separate
 * from the snapshot so merely rendering the welcome screen never creates
 * guest data.
 */
export function hasGuestWorkspaceSnapshot(): boolean {
  try {
    return (
      localStorage.getItem(GUEST_STATE_STORAGE_KEY) != null ||
      localStorage.getItem(LEGACY_GUEST_STATE_STORAGE_KEY) != null
    );
  } catch {
    return false;
  }
}

export function hasEnteredGuestSession(): boolean {
  try {
    if (localStorage.getItem(GUEST_SESSION_FLAG_KEY) === '1') return true;
  } catch {
    return false;
  }
  return hasGuestWorkspaceSnapshot();
}

export function markGuestSessionEntered(): void {
  try {
    localStorage.setItem(GUEST_SESSION_FLAG_KEY, '1');
  } catch {
    // Ignore storage failures — the welcome screen will simply show again.
  }
}
