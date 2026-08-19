import type { StrengthBand } from "./types";

/**
 * A local list of past letters, so "see past letters made" does not require a
 * server-side document store.
 *
 * Deliberately holds only what identifies a session, not the intake content:
 * subject and writer name, band, dates, session/job ids. NOT evidence,
 * reservations or tone notes. The intake itself stays in `sessionStorage`
 * only and is gone on tab close (see store/useSessionStore.ts) — this list
 * does not change that. localStorage is used here because the point of
 * history is to survive the tab closing; the tradeoff is that the two
 * writer/subject names outlive the tab, which the user asked for.
 */

export interface HistoryEntry {
  sessionId: string;
  jobId: string | null;
  subjectName: string;
  writerName: string;
  strengthBand: StrengthBand;
  createdAt: string;
  updatedAt: string;
  status: "reviewing" | "done";
}

const STORAGE_KEY = "reference-letter-drafter:history";
const MAX_ENTRIES = 50;

function readAll(): HistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as HistoryEntry[]) : [];
  } catch {
    return [];
  }
}

function writeAll(entries: HistoryEntry[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
  } catch {
    // Storage full or unavailable (private browsing). History is a
    // convenience, not the source of truth — the letter still lives in
    // SuperDocs either way.
  }
}

export function listHistory(): HistoryEntry[] {
  return readAll().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

/**
 * Insert or update by session id, most-recent first.
 *
 * `createdAt` is the letter's original draft time, not this update's time.
 * If an entry for this session already exists, its `createdAt` wins over
 * whatever the caller passed, so a revision or completion never overwrites
 * when the letter was actually started.
 */
export function upsertHistory(entry: Omit<HistoryEntry, "updatedAt"> & { updatedAt?: string }): void {
  const now = new Date().toISOString();
  const all = readAll();
  const existing = all.find((e) => e.sessionId === entry.sessionId);
  const full: HistoryEntry = {
    ...entry,
    createdAt: existing?.createdAt ?? entry.createdAt,
    updatedAt: entry.updatedAt ?? now,
  };
  writeAll([full, ...all.filter((e) => e.sessionId !== entry.sessionId)]);
}

export function removeHistory(sessionId: string): void {
  writeAll(readAll().filter((e) => e.sessionId !== sessionId));
}
