export function BeforeAfter({
  before,
  after,
  beforeLabel = "Before",
  afterLabel = "After",
}: {
  before: string;
  after: string;
  beforeLabel?: string;
  afterLabel?: string;
}) {
  return (
    <div className="before-after">
      <div className="diff-pane diff-before">
        <strong>{beforeLabel}</strong>
        <pre className="mono">{before || "—"}</pre>
      </div>
      <div className="diff-pane diff-after">
        <strong>{afterLabel}</strong>
        <pre className="mono">{after || "—"}</pre>
      </div>
    </div>
  );
}
