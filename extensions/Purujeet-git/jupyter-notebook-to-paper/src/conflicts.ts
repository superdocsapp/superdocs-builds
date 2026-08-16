import type { Evidence, MetricConflict } from "./types.js";

export function detectMetricConflicts(evidence: Evidence[]): MetricConflict[] {
  const groups = new Map<string, Evidence[]>();
  for (const item of evidence) {
    if (item.kind !== "metric" && item.kind !== "statistic") continue;
    const key = `${item.kind}:${item.label.trim().toLowerCase()}`;
    const group = groups.get(key) ?? [];
    group.push(item);
    groups.set(key, group);
  }

  return [...groups.entries()]
    .filter(([, group]) => new Set(group.map((item) => JSON.stringify(item.value))).size > 1)
    .map(([key, group]) => ({
      key,
      label: group[0]?.label ?? key,
      evidenceIds: group.map((item) => item.id),
      values: group.map((item) => item.value),
      message: `${group[0]?.label ?? key} has contradictory reported values: ${group.map((item) => String(item.value)).join(", ")}.`,
    }));
}
