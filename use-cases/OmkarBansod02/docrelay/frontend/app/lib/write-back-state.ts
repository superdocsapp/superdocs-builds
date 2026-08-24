import type { ConflictChoice, DryRunStatus, WriteBackStatus } from "./api";

export function canWriteBack(status: DryRunStatus, submitting: boolean): boolean {
  return status === "READY" && !submitting;
}

export function isVerifiedWriteSuccess(
  status: WriteBackStatus,
  structurallyVerified: boolean,
): boolean {
  return status === "WRITE_VERIFIED" && structurallyVerified;
}

export const conflictActions: readonly {
  choice: ConflictChoice;
  label: string;
}[] = [
  { choice: "CANCEL", label: "Cancel write-back" },
  { choice: "REVIEW_LATEST", label: "Review latest version" },
];
