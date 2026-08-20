import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { RegisterStatus, TechnicalStatus, FindingStatus, TransmittalStatus } from "./api/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ============================================================
// Status label helpers
// ============================================================

export function registerStatusLabel(status: RegisterStatus): string {
  const map: Record<RegisterStatus, string> = {
    NOT_RECEIVED: "Not Received",
    RECEIVED: "Received",
    UNDER_REVIEW: "Under Review",
    REVIEWED: "Reviewed",
    OVERDUE: "Overdue",
  };
  return map[status] ?? status;
}

export function technicalStatusLabel(status: TechnicalStatus | string): string {
  const map: Record<string, string> = {
    PENDING: "Pending",
    PENDING_REVIEW: "Pending Review",
    REVIEWED_DEVIATION: "Deviation",
    REVIEWED_COMPLIANT: "Compliant",
  };
  return map[status] ?? status;
}

export function findingStatusLabel(status: FindingStatus | string): string {
  const map: Record<string, string> = {
    PENDING_REVIEW: "Pending Review",
    APPROVED: "Approved",
    REJECTED: "Rejected",
    CLARIFICATION_REQUESTED: "Clarification Requested",
  };
  return map[status] ?? status;
}

export function transmittalStatusLabel(status: TransmittalStatus | string): string {
  const map: Record<string, string> = {
    DRAFT: "Draft",
    UPLOADED: "Uploaded",
    PROCESSING_EDIT: "Processing Edit",
    AWAITING_APPROVAL: "Awaiting Approval",
    EDIT_APPROVED: "Edit Approved",
    EDIT_REJECTED: "Edit Rejected",
    EXPORTED: "Exported",
  };
  return map[status] ?? status;
}

export function findingResultLabel(result: string): string {
  return result === "DEVIATION" ? "Deviation" : "Match";
}

// ============================================================
// Date helpers
// ============================================================

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function daysUntil(dateStr: string | null | undefined): number | null {
  if (!dateStr) return null;
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return null;
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  d.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
}
