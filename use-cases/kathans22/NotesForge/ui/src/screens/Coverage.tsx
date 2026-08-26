import { useMemo, useState } from "react";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { RunPanel } from "../components/RunPanel";
import type { Artifacts } from "../useArtifacts";
import type { CoverageEntry, CoverageStatus } from "../types";

const STATUS_LABEL: Record<CoverageStatus, string> = {
  EVIDENCED: "OK",
  STALE: "STALE",
  MISSING: "MISSING",
  INCONSISTENT: "CONFLICT",
};

export function Coverage({ data, reload }: { data: Artifacts; reload: () => void }) {
  const { requirements, clients, coverage } = data;
  const [selected, setSelected] = useState<CoverageEntry | null>(null);

  const entryFor = useMemo(() => {
    const map = new Map<string, CoverageEntry>();
    for (const e of coverage.entries) {
      map.set(`${e.requirement_id}::${e.client_id ?? "FIRM"}`, e);
    }
    return map;
  }, [coverage.entries]);

  const columns = useMemo(() => ["FIRM", ...clients.map((c) => c.id)], [clients]);
  const summary = coverage.summary;

  return (
    <>
      <div className="summary-strip">
        {(["EVIDENCED", "STALE", "MISSING", "INCONSISTENT"] as CoverageStatus[]).map((status) => (
          <div className="summary-tile" key={status}>
            <div className="count">{summary[status] ?? 0}</div>
            <div className="label">{status}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <h2>Requirement coverage</h2>
        <p className="panel-note">
          {coverage.generated_at
            ? `Generated ${new Date(coverage.generated_at).toLocaleString()} from ${coverage.notes_dir}`
            : "No coverage run on file yet."}
          {" · "}click a cell for its source note and line.
        </p>

        <RunPanel command="coverage" label="Run coverage check" onDone={reload} />

        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Requirement</th>
                {columns.map((col) => {
                  const client = clients.find((c) => c.id === col);
                  return <th key={col}>{client ? client.name : "Firm"}</th>;
                })}
              </tr>
            </thead>
            <tbody>
              {requirements.map((req) => (
                <tr key={req.id}>
                  <td>
                    <strong>{req.id}</strong>
                    <br />
                    <span style={{ color: "var(--text-muted)" }}>{req.title}</span>
                  </td>
                  {columns.map((col) => {
                    const entry = entryFor.get(`${req.id}::${col}`);
                    if (!entry) {
                      return (
                        <td key={col}>
                          <span className="coverage-cell NA">n/a</span>
                        </td>
                      );
                    }
                    return (
                      <td key={col}>
                        <button
                          type="button"
                          className={`coverage-cell ${entry.status}`}
                          onClick={() => setSelected(entry)}
                        >
                          {STATUS_LABEL[entry.status]}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selected && (
        <EvidenceDrawer
          entry={selected}
          requirement={requirements.find((r) => r.id === selected.requirement_id)}
          client={clients.find((c) => c.id === selected.client_id) ?? null}
          corpusNotes={data.corpusNotes}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
