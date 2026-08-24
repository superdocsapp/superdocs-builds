/**
 * Presentation-level preferences for the sidebar Recent list.
 *
 * Hiding a document is a *view* preference only: SyncRuns, backups and every
 * other durable audit record stay untouched and remain reachable from Activity.
 * Persistence is per-browser localStorage so no backend schema or delete
 * endpoint is involved.
 */

const STORAGE_KEY = "docrelay.recents.hidden.v1";
const CHANGE_EVENT = "docrelay:recents-hidden-changed";
const MAX_ENTRIES = 200;

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function read(): string[] {
  if (!canUseStorage()) return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((value): value is string => typeof value === "string" && value.length > 0);
  } catch {
    return [];
  }
}

function write(ids: string[]): void {
  if (!canUseStorage()) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids.slice(-MAX_ENTRIES)));
  } catch {
    /* Storage full or blocked: the preference is best-effort only. */
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function readHiddenRecents(): ReadonlySet<string> {
  return new Set(read());
}

/** Hide a document from Recent. Never deletes run history. */
export function hideRecentDocument(providerFileId: string): void {
  const ids = read();
  if (ids.includes(providerFileId)) return;
  write([...ids, providerFileId]);
}

/** Re-opening a document makes it eligible for Recent again. */
export function restoreRecentDocument(providerFileId: string): void {
  const ids = read();
  if (!ids.includes(providerFileId)) return;
  write(ids.filter((id) => id !== providerFileId));
}

export function subscribeToHiddenRecents(listener: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === STORAGE_KEY) listener();
  };
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener("storage", onStorage);
  };
}
