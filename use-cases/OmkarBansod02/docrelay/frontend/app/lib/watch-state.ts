import type { RunSummary, WatchScan, WatchScanItem } from "./api";
import type { RecentDocumentSelection } from "./conversation";

const GOOGLE_DOC_MIME = "application/vnd.google-apps.document";
const GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder";

export function scheduleLabel(enabled: boolean, intervalSeconds: number): string {
  if (!enabled) return "Manual";
  if (intervalSeconds < 3600) {
    const minutes = Math.round(intervalSeconds / 60);
    return minutes === 1 ? "Every minute" : `Every ${minutes} min`;
  }
  const hours = Math.round(intervalSeconds / 3600);
  return hours === 1 ? "Every hour" : `Every ${hours} hours`;
}

export function isActionableWatchRun(run: RunSummary): boolean {
  if (run.write_back_status === "WRITE_AUTHORIZATION_REQUIRED") return true;
  if (run.write_back_status === "CONFLICT" || run.workflow_state === "CONFLICT") return true;
  if (run.write_back_status === "UNKNOWN" || run.write_back_status === "ATTENTION") return true;
  if (run.write_back_status === "VERIFICATION_FAILED" || run.workflow_state === "VERIFICATION_FAILED") return true;
  if (run.review_status === "AWAITING_DECISIONS" || run.review_status === "AWAITING_CONTINUE") return true;
  return run.workflow_state === "AWAITING_REVIEW";
}

function runUpdatedAt(run: RunSummary): number {
  const parsed = Date.parse(run.updated_at);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** Latest run per document, keeping only documents that still need a person. */
export function actionableWatchRuns(runs: RunSummary[]): RunSummary[] {
  const latest = new Map<string, RunSummary>();
  for (const run of runs) {
    const existing = latest.get(run.provider_file_id);
    if (!existing || runUpdatedAt(run) >= runUpdatedAt(existing)) {
      latest.set(run.provider_file_id, run);
    }
  }
  return [...latest.values()]
    .filter(isActionableWatchRun)
    .sort((left, right) => runUpdatedAt(right) - runUpdatedAt(left));
}

export function proposalCountLabel(count: number): string {
  if (count <= 0) return "Changes prepared";
  if (count === 1) return "1 proposed change";
  return `${count} proposed changes`;
}

export type WatchDocumentAction = {
  kind: "review" | "authorize" | "conflict" | "attention";
  statusLabel: string;
  actionLabel: string;
  detail?: string;
};

export function watchDocumentAction(run: RunSummary): WatchDocumentAction {
  if (run.write_back_status === "WRITE_AUTHORIZATION_REQUIRED") {
    return {
      kind: "authorize",
      statusLabel: "Write access required",
      actionLabel: "Authorize document",
      detail: "DocRelay discovered this file through Watch, but Google requires you to authorize this exact document before write-back.",
    };
  }
  if (run.write_back_status === "CONFLICT" || run.workflow_state === "CONFLICT") {
    return { kind: "conflict", statusLabel: "Conflict", actionLabel: "Open conversation" };
  }
  if (
    run.write_back_status === "UNKNOWN"
    || run.write_back_status === "ATTENTION"
    || run.write_back_status === "VERIFICATION_FAILED"
    || run.workflow_state === "VERIFICATION_FAILED"
  ) {
    return { kind: "attention", statusLabel: "Attention required", actionLabel: "Open conversation" };
  }
  return {
    kind: "review",
    statusLabel: "Needs review",
    actionLabel: "Open conversation",
    detail: proposalCountLabel(run.proposal_count),
  };
}

export function watchActivityLabel(item: WatchScanItem, run?: RunSummary): string {
  if (run) {
    if (run.write_back_status === "WRITE_VERIFIED" && run.verification_status === "PASSED") return "Verified";
    if (run.write_back_status === "WRITE_AUTHORIZATION_REQUIRED") return "Write access required";
    if (run.write_back_status === "CONFLICT" || run.workflow_state === "CONFLICT") return "Conflict";
    if (run.write_back_status === "UNKNOWN" || run.write_back_status === "ATTENTION") return "Attention required";
    if (run.review_status === "AWAITING_DECISIONS" || run.workflow_state === "AWAITING_REVIEW") return "Needs review";
    if (run.review_status === "REVIEWED" || run.review_status === "DECISIONS_SUBMITTED") return "Reviewed";
  }
  if (item.outcome === "UNCHANGED") return "No changes";
  if (item.outcome === "ENQUEUED") return "Discovered";
  if (item.outcome === "FAILED") return "Attention required";
  if (item.outcome === "NO_RULE" || item.outcome === "UNSUPPORTED" || item.outcome === "OUT_OF_SCOPE") {
    return "Skipped";
  }
  return "Discovered";
}

export function watchErrorCopy(code: string | null): { title: string; detail: string } | null {
  if (!code) return null;
  if (code === "GOOGLE_WATCH_AUTHORIZATION_REQUIRED") {
    return {
      title: "Watch access required",
      detail: "DocRelay needs read access to discover files in the selected folder.",
    };
  }
  if (code === "WATCH_INVALID_ROOT") {
    return {
      title: "Selected folder is inaccessible",
      detail: "Choose a folder DocRelay can read, then scan again.",
    };
  }
  if (code === "WATCH_DISCOVERY_FAILED" || code === "WATCH_SCAN_FAILED") {
    return {
      title: "Scan could not finish",
      detail: "Nothing was written. Scan again when the folder is reachable.",
    };
  }
  if (code === "WATCHED_FILE_OUT_OF_SCOPE") {
    return {
      title: "Document is outside the watched folder",
      detail: "Write-back stays blocked until the file is back in scope.",
    };
  }
  return {
    title: "Watch needs attention",
    detail: code.replaceAll("_", " ").toLowerCase().replace(/^./, (letter) => letter.toUpperCase()),
  };
}

export function scanProgressLabel(scan: WatchScan | null, starting: boolean): string | null {
  if (starting && scan?.status !== "RUNNING") return "Starting scan…";
  if (scan?.status !== "RUNNING") return null;
  const parts = [
    scan.discovered_count > 0 ? `${scan.discovered_count} discovered` : null,
    scan.enqueued_count > 0 ? `${scan.enqueued_count} prepared` : null,
    scan.unchanged_count > 0 ? `${scan.unchanged_count} unchanged` : null,
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? `Scanning · ${parts.join(" · ")}` : "Scanning…";
}

export function exactFilePickMatches(pickedId: string, expectedId: string): boolean {
  return pickedId === expectedId;
}

export function isGoogleFolder(mimeType: string): boolean {
  return mimeType === GOOGLE_FOLDER_MIME;
}

export function watchDocumentSelection(run: RunSummary): RecentDocumentSelection {
  return {
    fileId: run.provider_file_id,
    name: run.document_name,
    mimeType: GOOGLE_DOC_MIME,
  };
}
