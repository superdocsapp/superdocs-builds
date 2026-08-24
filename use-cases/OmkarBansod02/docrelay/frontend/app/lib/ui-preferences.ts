/**
 * Per-browser layout preferences: navigation rail collapse and the width of
 * the conversation pane in the desktop workbench.
 *
 * These are presentation preferences only. Nothing here touches SyncRuns,
 * sources, review decisions or any provider state, and nothing is sent to the
 * backend — a different browser simply starts from the defaults.
 *
 * Both preferences are exposed as tiny external stores so components can read
 * them with `useSyncExternalStore`: the server snapshot is always the default,
 * which keeps the first client render identical to the server's.
 */

const SIDEBAR_KEY = "docrelay.ui.sidebar.v1";
const CONVERSATION_KEY = "docrelay.ui.conversation-width.v1";

/** Kept in sync with the same names in globals.css. */
export const CONVERSATION_MIN_WIDTH = 380;
export const CONVERSATION_MAX_WIDTH = 640;
export const CONVERSATION_DEFAULT_WIDTH = 452;
/** The document pane's preferred minimum; the conversation minimum wins if
    the viewport cannot honour both. */
export const DOCUMENT_MIN_WIDTH = 420;

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function readRaw(key: string): string | null {
  if (!canUseStorage()) return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeRaw(key: string, value: string): void {
  if (!canUseStorage()) return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* Storage full or blocked: the preference is best-effort only. */
  }
}

function notify(listeners: Set<() => void>): void {
  for (const listener of listeners) listener();
}

/* -------------------------------------------------------------------------- */
/* Navigation rail                                                            */
/* -------------------------------------------------------------------------- */

const sidebarListeners = new Set<() => void>();
let sidebarCollapsed: boolean | null = null;

function readSidebarCollapsed(): boolean {
  return readRaw(SIDEBAR_KEY) === "collapsed";
}

/** Cached so repeated snapshot reads return a stable value. */
export function sidebarSnapshot(): boolean {
  if (sidebarCollapsed === null) sidebarCollapsed = readSidebarCollapsed();
  return sidebarCollapsed;
}

export function sidebarServerSnapshot(): boolean {
  return false;
}

export function subscribeToSidebar(listener: () => void): () => void {
  sidebarListeners.add(listener);
  return () => {
    sidebarListeners.delete(listener);
  };
}

/**
 * The rail's width and label visibility are driven by this attribute so the
 * pre-hydration script in the document head can apply a stored preference
 * before first paint — the collapsed rail never flashes open.
 */
function applySidebarAttribute(collapsed: boolean): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.sidebar = collapsed ? "collapsed" : "expanded";
}

export function setSidebarCollapsed(collapsed: boolean): void {
  sidebarCollapsed = collapsed;
  applySidebarAttribute(collapsed);
  writeRaw(SIDEBAR_KEY, collapsed ? "collapsed" : "expanded");
  notify(sidebarListeners);
}

export function toggleSidebarCollapsed(): void {
  setSidebarCollapsed(!sidebarSnapshot());
}

/* -------------------------------------------------------------------------- */
/* Workbench split                                                            */
/* -------------------------------------------------------------------------- */

const widthListeners = new Set<() => void>();
let conversationWidth: number | null = null;

/**
 * Clamp to the supported range, optionally also reserving a usable document
 * pane. When the viewport cannot give both panes their minimum, the
 * conversation minimum wins and the document pane flexes below its preference.
 * Invalid values collapse to the default rather than being stored.
 */
export function clampConversationWidth(value: number, availableWidth?: number): number {
  if (!Number.isFinite(value)) return CONVERSATION_DEFAULT_WIDTH;
  let max = CONVERSATION_MAX_WIDTH;
  if (typeof availableWidth === "number" && Number.isFinite(availableWidth)) {
    max = Math.max(CONVERSATION_MIN_WIDTH, Math.min(max, availableWidth - DOCUMENT_MIN_WIDTH));
  }
  return Math.round(Math.min(Math.max(value, CONVERSATION_MIN_WIDTH), max));
}

function readConversationWidth(): number {
  const raw = readRaw(CONVERSATION_KEY);
  if (raw === null) return CONVERSATION_DEFAULT_WIDTH;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed)) return CONVERSATION_DEFAULT_WIDTH;
  return clampConversationWidth(parsed);
}

export function conversationWidthSnapshot(): number {
  if (conversationWidth === null) conversationWidth = readConversationWidth();
  return conversationWidth;
}

export function conversationWidthServerSnapshot(): number {
  return CONVERSATION_DEFAULT_WIDTH;
}

export function subscribeToConversationWidth(listener: () => void): () => void {
  widthListeners.add(listener);
  return () => {
    widthListeners.delete(listener);
  };
}

/**
 * Update the preferred width. Dragging updates in memory on every move and
 * only writes through to storage when the gesture settles.
 */
export function setConversationWidth(value: number, persist = false): void {
  const clamped = clampConversationWidth(value);
  if (clamped === conversationWidth && !persist) return;
  conversationWidth = clamped;
  if (persist) writeRaw(CONVERSATION_KEY, String(clamped));
  notify(widthListeners);
}
