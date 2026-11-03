export function ClassBadge({ docClass }) {
  if (!docClass) return <span className="badge badge-class">unclassified</span>;
  return <span className="badge badge-class">{docClass}</span>;
}

export function ConfidenceValue({ value }) {
  if (value === null || value === undefined) return <span className="conf">—</span>;
  const pct = Math.round(value * 100);
  const cls = pct >= 75 ? "high" : "low";
  return <span className={`conf ${cls}`}>{pct}%</span>;
}

export function ReviewBadge({ count }) {
  if (!count) return <span className="badge badge-clean">clean</span>;
  return (
    <span className="badge badge-review">
      {count} pending
    </span>
  );
}

export function HoldSeal({ size = 46 }) {
  return (
    <div className="seal-stamp" style={{ "--size": `${size}px` }} title="Legal hold — governance protected">
      <span>Legal
Hold</span>
    </div>
  );
}

export function EmptyState({ title, body }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  );
}

export function Loading({ label = "Loading…" }) {
  return <div className="spinner-line">{label}</div>;
}
