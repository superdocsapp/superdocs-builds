import type { ChangeEvent } from "../types/domain";
import { pluralize } from "./utils";

export interface ChangeLine {
  label: string;
  tone: "neutral" | "warning" | "positive";
}

/**
 * Turns a ChangeEvent's raw counts into the "what actually changed" summary
 * lines — the higher-level answer SuperDocs gives instead of a line-by-line
 * git-style diff.
 */
export function summarizeChange(change: ChangeEvent): ChangeLine[] {
  const lines: ChangeLine[] = [];

  if (change.textChangeCount > 0) {
    lines.push({ label: `${change.textChangeCount} ${pluralize(change.textChangeCount, "text change")}`, tone: "neutral" });
  }
  if (change.claimChangeIds.length > 0) {
    lines.push({ label: `${change.claimChangeIds.length} ${pluralize(change.claimChangeIds.length, "claim change")}`, tone: "neutral" });
  }
  if (change.requirementChangeIds.length > 0) {
    lines.push({
      label: `${change.requirementChangeIds.length} ${pluralize(change.requirementChangeIds.length, "requirement")} affected`,
      tone: "neutral",
    });
  }
  if (change.evidenceChangeIds.length > 0) {
    lines.push({
      label: `${change.evidenceChangeIds.length} evidence ${pluralize(change.evidenceChangeIds.length, "relationship")} changed`,
      tone: "neutral",
    });
  }
  if (change.riskDelta > 0) {
    lines.push({ label: `${change.riskDelta} ${pluralize(change.riskDelta, "risk")} increased`, tone: "warning" });
  } else if (change.riskDelta < 0) {
    lines.push({ label: `${Math.abs(change.riskDelta)} ${pluralize(Math.abs(change.riskDelta), "risk")} resolved`, tone: "positive" });
  }

  return lines;
}

export function sortChangesByRecency(changes: ChangeEvent[]): ChangeEvent[] {
  return [...changes].sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime());
}
