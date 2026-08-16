import type { Claim, Evidence, MetricConflict } from "./types.js";

export function buildClaimsFromEvidence(evidence: Evidence[], conflicts: MetricConflict[] = []): Claim[] {
  const claims: Claim[] = [];
  const conflictedEvidenceIds = new Set(conflicts.flatMap((conflict) => conflict.evidenceIds));
  const metrics = evidence.filter(
    (item): item is Evidence & { value: number } =>
      item.kind === "metric" && typeof item.value === "number",
  );

  const groups = new Map<string, typeof metrics>();
  for (const metric of metrics) {
    const match = metric.label.match(/^(.+?)\s+(accuracy|f1|precision|recall|score)$/i);
    const measure = match?.[2]?.toLowerCase() ?? metric.label.toLowerCase();
    const group = groups.get(measure) ?? [];
    group.push(metric);
    groups.set(measure, group);
  }

  for (const [measure, group] of groups) {
    if (group.length < 2) continue;
    if (group.some((metric) => conflictedEvidenceIds.has(metric.id))) continue;
    const ordered = [...group].sort((a, b) => b.value - a.value);
    const winner = ordered[0];
    const runnerUp = ordered[1];
    if (!winner || !runnerUp || winner.value === runnerUp.value) continue;

    claims.push({
      id: `claim:comparison:${measure}`,
      statement: `${winner.label} was higher than ${runnerUp.label} for ${measure}.`,
      evidenceIds: [winner.id, runnerUp.id],
    });
  }

  for (const statistic of evidence.filter((item) => item.kind === "statistic")) {
    claims.push({
      id: `claim:statistic:${statistic.id}`,
      statement: `${statistic.label} was reported.`,
      evidenceIds: [statistic.id],
    });
  }

  return claims;
}
