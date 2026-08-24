import { ApiError, type RegisteredSource, type RunSummary } from "./api";

export type SelectedDriveFile = {
  fileId: string;
  name: string;
  mimeType: string;
};

export type ImportStageId =
  | "FILE_SELECTED"
  | "READING_SOURCE"
  | "FREEZING_REVISION"
  | "PREPARING_WORKSPACE";

export type ImportStageStatus = "complete" | "active" | "pending";

export type ImportPhase = "READING_SOURCE" | "FAILED";

export type ImportFailure = {
  title: string;
  protection: string;
  retryable: boolean;
};

export type RecentDocument = {
  providerFileId: string;
  name: string;
  updatedAt: string;
};

/** The document currently open in the workbench, if any. */
export type ActiveDocument = {
  providerFileId: string;
  name: string;
};

export const IMPORT_STAGES: readonly { id: ImportStageId; label: string }[] = [
  { id: "FILE_SELECTED", label: "File selected" },
  { id: "READING_SOURCE", label: "Reading Google document" },
  { id: "FREEZING_REVISION", label: "Freezing source revision" },
  { id: "PREPARING_WORKSPACE", label: "Preparing workspace" },
];

const DEFAULT_PROTECTION = "DocRelay did not create or modify anything.";

/**
 * Picker returns the file immediately. The only subsequent observable work is
 * the single register-source request, which reads the Doc, freezes the
 * revision, and persists the workspace baseline together.
 */
export function importStageStatus(
  id: ImportStageId,
  phase: ImportPhase,
): ImportStageStatus {
  if (id === "FILE_SELECTED") return "complete";
  if (phase === "FAILED") return "pending";
  if (id === "READING_SOURCE") return "active";
  return "pending";
}

export function importStatusLabel(phase: ImportPhase, documentName: string): string {
  if (phase === "FAILED") return `Could not import ${documentName}`;
  return `Reading ${documentName}`;
}

export function extractSelectedFile(data: {
  action: string;
  docs?: Array<{ id?: string; name?: string; mimeType?: string }>;
}): SelectedDriveFile | null {
  if (data.action === "cancel" || data.action !== "picked") return null;
  const doc = data.docs?.[0];
  if (!doc?.id) return null;
  return {
    fileId: doc.id,
    name: doc.name?.trim() || "Untitled document",
    mimeType: doc.mimeType ?? "",
  };
}

export function buildRegistrationPayload(file: SelectedDriveFile): { file_id: string } {
  return { file_id: file.fileId };
}

/** Versioned Google copies created before write-back. Keep them in history; hide from Recents. */
export const DOCRELAY_BACKUP_NAME_MARKER = " — DocRelay backup — ";

export function isDocRelayBackupName(name: string): boolean {
  return name.includes(DOCRELAY_BACKUP_NAME_MARKER);
}

export const GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document";

function timestamp(value: string | null | undefined): number {
  const parsed = Date.parse(value ?? "");
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * Folds one authoritative document into the Recent map.
 *
 * Identity is the immutable `provider_file_id`, so the same Google document
 * reached through a run, through the registered-source list and through the
 * open workbench collapses into exactly one entry — the newest name and
 * timestamp win. Internal backup copies are never user documents.
 */
function foldRecentDocument(
  into: Map<string, RecentDocument>,
  candidate: RecentDocument,
): void {
  const providerFileId = candidate.providerFileId.trim();
  const name = candidate.name.trim();
  if (!providerFileId || !name) return;
  if (isDocRelayBackupName(name)) return;

  const existing = into.get(providerFileId);
  if (!existing) {
    into.set(providerFileId, { providerFileId, name, updatedAt: candidate.updatedAt });
    return;
  }
  if (timestamp(candidate.updatedAt) > timestamp(existing.updatedAt)) {
    into.set(providerFileId, { providerFileId, name, updatedAt: candidate.updatedAt });
  }
}

/**
 * Recent documents, derived only from authoritative backend state.
 *
 * `sources` is the canonical set of Google documents DocRelay has actually
 * registered and read — a document that has been opened but has not produced a
 * run yet lives here and nowhere else. `runs` carries every document that has
 * since been worked on, manual and watch-origin alike, and supplies the more
 * recent timestamp once work has happened. `active` is the document open in
 * this window right now, so the sidebar reflects it before the refetch lands;
 * it is folded under the same file identity and therefore cannot duplicate an
 * entry the backend already returned.
 */
export function recentDocuments(
  {
    runs = [],
    sources = [],
    active = null,
  }: {
    runs?: RunSummary[];
    sources?: RegisteredSource[];
    active?: ActiveDocument | null;
  },
  limit = 8,
): RecentDocument[] {
  const latestByFile = new Map<string, RecentDocument>();

  for (const source of sources) {
    if (source.mime_type && source.mime_type !== GOOGLE_DOC_MIME_TYPE) continue;
    foldRecentDocument(latestByFile, {
      providerFileId: source.provider_file_id ?? "",
      name: source.name ?? "",
      updatedAt: source.last_seen_at ?? "",
    });
  }

  for (const run of runs) {
    foldRecentDocument(latestByFile, {
      providerFileId: run.provider_file_id ?? "",
      name: run.document_name ?? "",
      updatedAt: run.updated_at,
    });
  }

  // The open document is added only if the backend has not returned it yet,
  // and never overwrites an authoritative name or timestamp: it carries no
  // invented "last worked on" time, only its place at the top of the list.
  const activeFileId = active?.providerFileId.trim() ?? "";
  if (active && activeFileId && !latestByFile.has(activeFileId)) {
    foldRecentDocument(latestByFile, {
      providerFileId: activeFileId,
      name: active.name,
      updatedAt: "",
    });
  }

  return [...latestByFile.values()]
    .sort((a, b) => {
      if (a.providerFileId === activeFileId) return -1;
      if (b.providerFileId === activeFileId) return 1;
      return timestamp(b.updatedAt) - timestamp(a.updatedAt);
    })
    .slice(0, limit);
}

/** Runs-only projection, kept for callers that have no source list. */
export function recentDocumentsFromRuns(
  runs: RunSummary[],
  limit = 8,
): RecentDocument[] {
  return recentDocuments({ runs }, limit);
}

export function formatRelativeTime(iso: string, now = Date.now()): string {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";

  const deltaSeconds = Math.round((now - then) / 1000);
  if (deltaSeconds < 45) return "Just now";
  if (deltaSeconds < 90) return "1 minute ago";

  const minutes = Math.round(deltaSeconds / 60);
  if (minutes < 60) return `${minutes} minutes ago`;
  if (minutes < 90) return "1 hour ago";

  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hours ago`;
  if (hours < 42) return "Yesterday";

  const days = Math.round(hours / 24);
  if (days < 14) return `${days} days ago`;

  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(then));
}

export function mapImportFailure(error: unknown): ImportFailure {
  const code = error instanceof ApiError ? error.code : "";

  switch (code) {
    case "UNSUPPORTED_SOURCE_TYPE":
      return {
        title: "Only Google Docs are supported",
        protection: DEFAULT_PROTECTION,
        retryable: false,
      };
    case "GOOGLE_FILE_NOT_FOUND":
      return {
        title: "This Google Doc could not be found",
        protection: DEFAULT_PROTECTION,
        retryable: false,
      };
    case "GOOGLE_PERMISSION_DENIED":
      return {
        title: "DocRelay cannot read this Google Doc",
        protection: DEFAULT_PROTECTION,
        retryable: true,
      };
    case "SOURCE_TRASHED":
      return {
        title: "This Google Doc is in the trash",
        protection: DEFAULT_PROTECTION,
        retryable: false,
      };
    case "SOURCE_CHANGED_DURING_CAPTURE":
      return {
        title: "This Google Doc changed while DocRelay was reading it",
        protection: DEFAULT_PROTECTION,
        retryable: true,
      };
    case "GOOGLE_REAUTH_REQUIRED":
      return {
        title: "Google Drive needs to be reconnected",
        protection: DEFAULT_PROTECTION,
        retryable: false,
      };
    case "GOOGLE_RATE_LIMITED":
    case "GOOGLE_UNAVAILABLE":
      return {
        title: "Google Drive is temporarily unavailable",
        protection: DEFAULT_PROTECTION,
        retryable: true,
      };
    default:
      return {
        title: "Could not read this Google Doc",
        protection: DEFAULT_PROTECTION,
        retryable: true,
      };
  }
}

export function mapPickerFailure(error: unknown): string | null {
  const message = error instanceof Error ? error.message : "";
  const normalized = message.toLowerCase();
  if (
    normalized.includes("popup_closed") ||
    normalized.includes("popup was closed") ||
    normalized.includes("access_denied")
  ) {
    return null;
  }
  if (normalized.includes("failed to load") || normalized.includes("picker library")) {
    return "Google Drive could not be opened. Check your connection and try again.";
  }
  if (message.includes("Frontend Google configuration")) {
    return "Google Drive is not fully configured in this environment.";
  }
  return "Google Drive could not be opened. Try again.";
}
