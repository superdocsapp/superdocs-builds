import type { Finding } from "../api";

interface Props {
  items: Finding[];
}

export function UnknownPanel({ items }: Props) {
  if (items.length === 0) return null;

  return (
    <div className="unknown-panel">
      <h2>Unknown ({items.length})</h2>
      <p className="subtitle">Verify manually — unparseable sections, no mappable claim, or feed silent.</p>
      {items.map((f) => (
        <div key={f.id} className="unknown-item">
          <span className="badge unknown-badge">UNKNOWN</span>
          <p className="filename">{f.filename || f.document_id}</p>
          <p className="reason">
            {f.ai_explanation || "No explanation available"}
          </p>
        </div>
      ))}
    </div>
  );
}