import type { MachineWriteBackStatus, RunSummary } from "../lib/api";
import { StateMark } from "./ui";

export function RunStatus({ run }: { run: RunSummary }) {
  const display = runStatusDisplay(run);
  return (
    <span className="inline-flex items-center gap-2 text-[13px] text-ink">
      <StateMark state={display.mark} />
      <span>{display.label}</span>
    </span>
  );
}

export function runStatusDisplay(run: RunSummary): { label: string; mark: "idle" | "current" | "complete" | "warning" | "info" } {
  const status = run.write_back_status;
  if (status === "WRITE_AUTHORIZATION_REQUIRED") return { label: "Write authorization required", mark: "info" };
  if (status === "CONFLICT") return { label: "Conflict", mark: "warning" };
  if (status === "WRITE_VERIFIED" && run.verification_status === "PASSED") return { label: "Verified", mark: "complete" };
  if (status === "UNKNOWN") return { label: "External outcome unknown", mark: "info" };
  if (run.review_status === "AWAITING_DECISIONS" || run.review_status === "AWAITING_CONTINUE") return { label: "Awaiting review", mark: "current" };
  if (run.ready_for_write_back || status === "READY") return { label: "Ready for safe write-back", mark: "complete" };
  if (run.ready_for_dry_run) return { label: "Ready for safety check", mark: "current" };
  if (["QUEUED", "BASELINING", "EDITING", "COMMITTING", "VERIFYING"].includes(run.workflow_state)) return { label: humanState(run.workflow_state), mark: "current" };
  if (["FAILED", "VERIFICATION_FAILED", "ATTENTION"].includes(status)) return { label: status === "VERIFICATION_FAILED" ? "Verification failed" : "Needs attention", mark: "warning" };
  if (run.workflow_state === "SKIPPED") return { label: "Skipped", mark: "idle" };
  if (run.workflow_state === "CANCELLED" || status === "CANCELLED") return { label: "Cancelled", mark: "idle" };
  return { label: humanState(run.workflow_state), mark: "idle" };
}

export function runActionLabel(run: RunSummary): string {
  const status = run.write_back_status;
  if (status === "WRITE_AUTHORIZATION_REQUIRED") return "Authorize exact file";
  if (status === "CONFLICT") return "Review latest";
  if (run.review_status === "AWAITING_DECISIONS" || run.review_status === "AWAITING_CONTINUE") return "Review";
  return "Open";
}

export function humanState(state: string): string {
  return state.toLowerCase().replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

export function writeBackStatusOrder(status: MachineWriteBackStatus): number {
  return status === "WRITE_AUTHORIZATION_REQUIRED" ? 0 : status === "CONFLICT" ? 1 : status === "AWAITING_REVIEW" ? 2 : 3;
}
