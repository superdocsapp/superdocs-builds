import { RunPanel } from "../components/RunPanel";
import type { Artifacts } from "../useArtifacts";
import type { ConsentCellStatus } from "../types";

const CONSENT_LABEL: Record<ConsentCellStatus, string> = {
  CURRENT_CONSENTED: "current, consented",
  CURRENT_PENDING_CONSENT: "current, pending consent",
  BEHIND: "behind, consented to prior version",
  BEHIND_NOT_CONSENTED: "behind, not consented",
  NOT_ISSUED: "not issued",
};

const CONSENT_CLASS: Record<ConsentCellStatus, string> = {
  CURRENT_CONSENTED: "EVIDENCED",
  CURRENT_PENDING_CONSENT: "STALE",
  BEHIND: "STALE",
  BEHIND_NOT_CONSENTED: "MISSING",
  NOT_ISSUED: "MISSING",
};

export function Clients({ data, reload }: { data: Artifacts; reload: () => void }) {
  const { clients, consentMatrix, coverage } = data;

  const riskEntryFor = (clientId: string) =>
    coverage.entries.find((e) => e.requirement_id === "RIA-RISK-01" && e.client_id === clientId);

  return (
    <div className="panel">
      <h2>Client roster</h2>
      <p className="panel-note">
        {clients.length} advisory client(s) · agreement version and consent state from{" "}
        {consentMatrix.generated_at ? new Date(consentMatrix.generated_at).toLocaleString() : "no matrix run yet"}.
      </p>

      <RunPanel command="registry-seed" label="Seed version registry" onDone={reload} />
      <RunPanel command="matrix" label="Refresh consent matrix" onDone={reload} />

      <table>
        <thead>
          <tr>
            <th>Client</th>
            <th>Advisory type</th>
            <th>AI-assisted</th>
            <th>Onboarded</th>
            <th>Agreement version</th>
            <th>Risk review</th>
          </tr>
        </thead>
        <tbody>
          {clients.map((c) => {
            const row = consentMatrix.rows.find((r) => r.client_id === c.id);
            const riskEntry = riskEntryFor(c.id);
            return (
              <tr key={c.id}>
                <td>
                  <strong>{c.id}</strong> {c.name}
                </td>
                <td>{c.advisory_type}</td>
                <td>{c.ai_assisted ? "Yes" : "No"}</td>
                <td>{c.onboarded_on}</td>
                <td>
                  {row?.cells.length ? (
                    row.cells.map((cell) => (
                      <div key={cell.template_id} style={{ marginBottom: "0.25rem" }}>
                        <span className={`status-badge ${CONSENT_CLASS[cell.status]}`}>
                          {cell.version ?? "—"}
                        </span>{" "}
                        <span style={{ color: "var(--text-muted)", fontSize: "0.78rem" }}>
                          {CONSENT_LABEL[cell.status]}
                          {cell.consented_on ? ` (${cell.consented_on})` : ""}
                        </span>
                      </div>
                    ))
                  ) : (
                    <span className="pill">no template on file</span>
                  )}
                </td>
                <td>
                  {c.risk_profile_reviewed_on ?? "never reviewed"}
                  {riskEntry && (
                    <>
                      {" "}
                      <span className={`status-badge ${riskEntry.status}`}>{riskEntry.status}</span>
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
