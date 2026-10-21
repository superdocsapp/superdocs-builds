import { metricLabel } from "../labels";

const METRIC_MARKERS: Record<string, string> = {
  total_roles: "roles",
  proposed_families: "families",
  tracks: "tracks",
  strong_fits: "fit",
  provisional: "provisional",
  misfits: "misfit",
  unclustered: "unclustered",
  bridge_roles: "bridge",
};

export function Metric({
  value,
  label,
  marker,
}: {
  value: string | number;
  label: string;
  marker?: string;
}) {
  const tone = marker ? ` metric--${marker}` : "";
  return (
    <div className={`metric${tone}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

export function MetricsRow({ metrics }: { metrics: Record<string, string | number> }) {
  return (
    <div className="metrics">
      {Object.entries(metrics).map(([key, value]) => (
        <Metric key={key} value={value} label={metricLabel(key)} marker={METRIC_MARKERS[key] ?? "neutral"} />
      ))}
    </div>
  );
}
