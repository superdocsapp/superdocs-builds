const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false
});

const DATE_ONLY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });

const TIME_ONLY = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December"
];

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "16 Aug 2026 10:42" */
export function formatTimestamp(value: string | null | undefined): string {
  const date = parse(value);
  return date ? DATE_TIME.format(date).replace(",", "") : "";
}

/** "Apr 5, 2026" */
export function formatDate(value: string | null | undefined): string {
  const date = parse(value);
  return date ? DATE_ONLY.format(date) : "";
}

/** "10:42" */
export function formatTime(value: string | null | undefined): string {
  const date = parse(value);
  return date ? TIME_ONLY.format(date) : "";
}

/** "2026-03" -> "March 2026" */
export function formatPeriod(period: string | null | undefined): string {
  if (!period) return "";
  const [year, month] = period.split("-");
  const index = Number(month) - 1;
  return MONTHS[index] ? `${MONTHS[index]} ${year}` : period;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes < 0) return "0 KB";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const EVENT_LABELS: Record<string, string> = {
  CLOSE_CREATED: "Close created",
  DOCUMENT_UPLOADED: "Document uploaded",
  DOCUMENT_CLASSIFIED: "Document classified",
  DOCUMENT_DELETED: "Document removed",
  DOCUMENT_AUTO_CLASSIFIED: "Document auto-classified",
  CHECKLIST_COMPLETED: "Checklist item completed",
  CHECKLIST_REOPENED: "Checklist item reopened",
  GENERATION_STARTED: "Pack generation started",
  GENERATION_COMPLETED: "Pack generated",
  GENERATION_FAILED: "Pack generation failed",
  GENERATION_ABANDONED: "Pack generation abandoned",
  ARTIFACT_GENERATED: "Supporting document created",
  REVIEW_APPROVED: "Change approved",
  REVIEW_REJECTED: "Change rejected",
  REVIEW_APPROVAL_FAILED: "Change could not be approved",
  SUPERDOCS_EXPORTED: "Final document produced",
  SUPERDOCS_EXPORT_FAILED: "Final document could not be produced",
  SIGNOFF_APPROVED: "Sign-off approved",
  EXPORT_COMPLETED: "Pack exported",
  EXPORT_INVALIDATED: "Exported pack superseded",
  CLOSE_BLOCKED: "Close blocked",
  CLOSE_CLOSED: "Period closed"
};

export function formatEvent(event: string): string {
  const fallback = event.toLowerCase().replace(/_/g, " ");
  const label = EVENT_LABELS[event] ?? fallback;
  return label.charAt(0).toUpperCase() + label.slice(1);
}

const STATUS_LABELS: Record<string, string> = {
  READY: "Ready",
  PENDING: "Pending",
  COMPLETE: "Complete",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  SUCCEEDED: "Done",
  FAILED: "Failed",
  RUNNING: "In progress",
  COLLECTING: "Collecting evidence",
  GENERATING: "Building the pack",
  REVIEW_REQUIRED: "Needs review",
  READY_TO_CLOSE: "Ready to close",
  CLOSED: "Closed",
  UNCLASSIFIED: "Needs a type"
};

/** Backend enums are upper case and snake_cased; never show one to a user raw. */
export function statusLabel(status: string): string {
  if (!status) return "";
  const spaced = status.toLowerCase().replace(/_/g, " ");
  return STATUS_LABELS[status] ?? spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Strip internal references out of a server-authored audit detail before display.
 *
 * Audit details are written for the record and carry job UUIDs, byte counts and sha256
 * fragments. Those belong in the exported evidence bundle, not in the activity feed a
 * controller reads.
 */
export function cleanDetail(detail: string | null | undefined): string {
  if (!detail) return "";
  return detail
    .replace(/job\s+[0-9a-f-]{8,}/gi, "")
    .replace(/,?\s*memo\s+[0-9a-f]{6,}/gi, "")
    .replace(/\s*\(\s*\d+\s*bytes\s*\)/gi, "")
    // Removing a reference can leave behind the brackets that wrapped it.
    .replace(/\(\s*\)/g, "")
    .replace(/\s{2,}/g, " ")
    .replace(/^[\s,;-]+|[\s,;-]+$/g, "")
    .trim();
}
