import type { BriefResponse, BriefStatus, HistoryItem } from "@/types/brief";

const HISTORY_KEY = "ipb-history";

export function loadHistory(): HistoryItem[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as HistoryItem[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveHistoryItem(item: HistoryItem) {
  const existing = loadHistory().filter((h) => h.brief_id !== item.brief_id);
  const next = [item, ...existing].slice(0, 50);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
}

export function upsertHistoryFromBrief(brief: BriefResponse) {
  saveHistoryItem({
    brief_id: brief.brief_id,
    session_id: brief.session_id,
    company_name: brief.company_name,
    status: brief.status,
    created_at: brief.created_at,
    role_summary: brief.content?.role_summary,
  });
}

export function updateHistoryStatus(briefId: string, status: BriefStatus) {
  const next = loadHistory().map((item) =>
    item.brief_id === briefId ? { ...item, status } : item,
  );
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
}

export function removeHistoryItem(briefId: string) {
  const next = loadHistory().filter((item) => item.brief_id !== briefId);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
}

export function clearHistory() {
  localStorage.removeItem(HISTORY_KEY);
}
