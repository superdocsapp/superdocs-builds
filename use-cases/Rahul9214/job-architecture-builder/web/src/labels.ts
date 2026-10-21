export const METRIC_LABELS: Record<string, string> = {
  total_roles: "Total roles",
  proposed_families: "Families",
  tracks: "Tracks",
  strong_fits: "Strong fit",
  provisional: "Provisional",
  misfits: "Misfit",
  unclustered: "Unclustered",
  bridge_roles: "Bridge",
};

export const DIMENSION_LABELS: Record<string, string> = {
  scope: "Scope",
  autonomy: "Autonomy",
  decision_authority: "Decision authority",
  complexity: "Complexity",
  impact: "Impact",
  leadership: "Leadership",
  people_management: "People management",
};

export function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key.replace(/_/g, " ");
}

export function dimensionLabel(key: string): string {
  return DIMENSION_LABELS[key] ?? key.replace(/_/g, " ");
}
