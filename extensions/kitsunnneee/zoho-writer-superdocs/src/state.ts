export interface PersistedRunState {
  version: 1;
  sessionId: string;
  jobId: string;
  status: "pending" | "in_progress" | "awaiting_approval";
  awaitingKind?: string;
}

export interface RunStateStore {
  load(): PersistedRunState | null;
  save(state: PersistedRunState): void;
  clear(): void;
}

const STORAGE_KEY = "superdocs.writer.active-run.v1";
const ACTIVE_STATUSES = new Set([
  "pending",
  "in_progress",
  "awaiting_approval",
]);

const normalizePersistedState = (value: unknown): PersistedRunState | null => {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (
    candidate.version !== 1 ||
    typeof candidate.sessionId !== "string" ||
    candidate.sessionId.length === 0 ||
    candidate.sessionId.length > 256 ||
    typeof candidate.jobId !== "string" ||
    candidate.jobId.length === 0 ||
    candidate.jobId.length > 256 ||
    typeof candidate.status !== "string" ||
    !ACTIVE_STATUSES.has(candidate.status) ||
    (candidate.awaitingKind !== undefined &&
      (typeof candidate.awaitingKind !== "string" ||
        candidate.awaitingKind.length > 64))
  ) {
    return null;
  }
  return {
    version: 1,
    sessionId: candidate.sessionId,
    jobId: candidate.jobId,
    status: candidate.status as PersistedRunState["status"],
    ...(typeof candidate.awaitingKind === "string"
      ? { awaitingKind: candidate.awaitingKind }
      : {}),
  };
};

export class BrowserRunStateStore implements RunStateStore {
  constructor(private readonly storage: Storage = window.localStorage) {}

  load(): PersistedRunState | null {
    try {
      const serialized = this.storage.getItem(STORAGE_KEY);
      if (!serialized) return null;
      const state = normalizePersistedState(JSON.parse(serialized) as unknown);
      if (!state) this.clear();
      return state;
    } catch {
      this.clear();
      return null;
    }
  }

  save(state: PersistedRunState): void {
    try {
      this.storage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Persistence is best-effort; the in-memory workflow remains usable.
    }
  }

  clear(): void {
    try {
      this.storage.removeItem(STORAGE_KEY);
    } catch {
      // Storage may be disabled by the iframe/browser policy.
    }
  }
}

export class MemoryRunStateStore implements RunStateStore {
  state: PersistedRunState | null = null;

  load(): PersistedRunState | null {
    return this.state;
  }

  save(state: PersistedRunState): void {
    this.state = { ...state };
  }

  clear(): void {
    this.state = null;
  }
}
