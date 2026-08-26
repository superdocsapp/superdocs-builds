import type { Client, CoverageEntry, Requirement } from "../types";

function contextLines(corpusNotes: Record<string, string>, file: string, line: number, radius = 1): string {
  const content = corpusNotes[file];
  if (!content) return "";
  const lines = content.split(/\r?\n/);
  const start = Math.max(0, line - 1 - radius);
  const end = Math.min(lines.length, line + radius);
  return lines
    .slice(start, end)
    .map((l, i) => {
      const lineNo = start + i + 1;
      const marker = lineNo === line ? ">" : " ";
      return `${marker} ${String(lineNo).padStart(4)}  ${l}`;
    })
    .join("\n");
}

export function EvidenceDrawer({
  entry,
  requirement,
  client,
  corpusNotes,
  onClose,
}: {
  entry: CoverageEntry;
  requirement: Requirement | undefined;
  client: Client | null;
  corpusNotes: Record<string, string>;
  onClose: () => void;
}) {
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="close" onClick={onClose}>
          Close
        </button>
        <h3>{requirement?.title ?? entry.requirement_id}</h3>
        <p className="drawer-sub">
          {entry.requirement_id} · {requirement?.citation}
        </p>

        <p>
          <span className={`status-badge ${entry.status}`}>{entry.status}</span>{" "}
          <span className="pill">{client ? `${client.id} — ${client.name}` : "FIRM-LEVEL"}</span>{" "}
          <span className="pill">{entry.method}</span>
        </p>

        <p>{entry.detail}</p>

        <h4 style={{ marginBottom: "0.4rem", fontSize: "0.85rem" }}>
          Source {entry.evidence.length === 1 ? "line" : "lines"}
        </h4>
        {entry.evidence.length === 0 && <p className="panel-note">No evidence lines — nothing to cite.</p>}
        {entry.evidence.map((ev, i) => (
          <div className="evidence-line" key={i}>
            <span className="loc">
              {ev.file}:{ev.line}
            </span>
            {contextLines(corpusNotes, ev.file, ev.line) || ev.excerpt}
          </div>
        ))}

        {requirement && (
          <>
            <h4 style={{ marginBottom: "0.4rem", fontSize: "0.85rem" }}>Evidence expected</h4>
            <ul style={{ fontSize: "0.82rem", color: "var(--text-muted)", paddingLeft: "1.1rem" }}>
              {requirement.evidence_expected.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </>
        )}

        <p className="draft-banner">
          This entry reflects an automated read of source notes. It is not a compliance determination —
          review by a qualified professional is required.
        </p>
      </div>
    </div>
  );
}
