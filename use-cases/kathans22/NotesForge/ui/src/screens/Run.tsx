import type { Artifacts } from "../useArtifacts";
import type { LedgerRow } from "../types";

interface RowGroup extends LedgerRow {
  count: number;
}

/**
 * Collapses consecutive rows sharing a label (e.g. a run of `getJob` polls
 * while a job is in_progress) into one display row — same underlying
 * numbers (summed ops, last running total), just not one line per poll.
 * Never reorders or drops a row, only merges adjacent identical labels.
 */
function groupConsecutive(rows: LedgerRow[]): RowGroup[] {
  const groups: RowGroup[] = [];
  for (const row of rows) {
    const last = groups[groups.length - 1];
    if (last && last.label === row.label) {
      last.count += 1;
      last.opsCharged += row.opsCharged;
      last.runningTotal = row.runningTotal;
      last.monthlyRemaining = row.monthlyRemaining;
    } else {
      groups.push({ ...row, count: 1 });
    }
  }
  return groups;
}

export function Run({ data, reload }: { data: Artifacts; reload: () => void }) {
  const { ledger } = data;

  if (!ledger) {
    return (
      <div className="panel">
        <h2>Operations ledger</h2>
        <p className="state-message">
          No run on file yet — trigger a command from the Coverage, Clients, Packs or Amendments tab.
        </p>
        <button type="button" className="run-toggle" onClick={reload}>
          refresh
        </button>
      </div>
    );
  }

  const budgetUsedPct = Math.min(100, Math.round((ledger.total_spent / ledger.ops_cap) * 100));

  return (
    <>
      <div className="summary-strip">
        <div className="summary-tile">
          <div className="count">{ledger.command}</div>
          <div className="label">last command</div>
        </div>
        <div className="summary-tile">
          <div className="count">{ledger.total_spent}</div>
          <div className="label">ops charged this run</div>
        </div>
        <div className="summary-tile">
          <div className="count">{ledger.ops_cap}</div>
          <div className="label">per-run cap</div>
        </div>
        <div className="summary-tile">
          <div className="count">{ledger.remaining ?? "?"}</div>
          <div className="label">monthly remaining</div>
        </div>
      </div>

      <div className="panel">
        <h2>Operations ledger — {ledger.command}</h2>
        <p className="panel-note">
          From state/ledger.json, written by the CLI at the end of the run ({new Date(ledger.generated_at).toLocaleString()}) —
          the same rows OpsLedger.report() printed to the console, not recomputed here. {budgetUsedPct}% of the
          {" "}
          {ledger.ops_cap}-op cap used.
        </p>

        <button type="button" className="run-toggle" onClick={reload} style={{ marginBottom: "0.8rem" }}>
          refresh
        </button>

        <table>
          <thead>
            <tr>
              <th>Step</th>
              <th>Ops charged</th>
              <th>Running total</th>
              <th>Monthly remaining after</th>
            </tr>
          </thead>
          <tbody>
            {groupConsecutive(ledger.rows).map((row, i) => (
              <tr key={i}>
                <td className="mono">
                  {row.label}
                  {row.count > 1 ? ` ×${row.count}` : ""}
                </td>
                <td>{row.opsCharged === 0 ? <span className="pill">free</span> : row.opsCharged}</td>
                <td>{row.runningTotal}</td>
                <td>{row.monthlyRemaining ?? "?"}</td>
              </tr>
            ))}
            {ledger.rows.length === 0 && (
              <tr>
                <td colSpan={4} className="panel-note">
                  (no ops recorded this run)
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
