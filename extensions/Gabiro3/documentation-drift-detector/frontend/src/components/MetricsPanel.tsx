import type { RunMetrics } from "../api";

function pct(v: number | null): string {
  // "—" not "0%": undefined and zero are different claims.
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;
}

export function MetricsPanel({ metrics }: { metrics: RunMetrics | null }) {
  if (!metrics) return null;

  const scored = metrics.scored_facts > 0;

  return (
    <div className="metrics-panel">
      <h2 className="section-title">Detection quality</h2>

      {!scored ? (
        <p className="text-muted">
          No literal change facts in this run, so precision and recall are
          undefined.
        </p>
      ) : (
        <>
          <div className="stat-row">
            <div className="stat-tile">
              <span className="stat-tile-value">{pct(metrics.precision)}</span>
              <span className="stat-tile-label">Precision</span>
            </div>
            <div className="stat-tile">
              <span className="stat-tile-value">{pct(metrics.recall)}</span>
              <span className="stat-tile-label">Recall</span>
            </div>
            <div className="stat-tile">
              <span className="stat-tile-value">{pct(metrics.f1)}</span>
              <span className="stat-tile-label">F1</span>
            </div>
            <div className="stat-tile">
              <span className="stat-tile-value">{pct(metrics.accuracy)}</span>
              <span className="stat-tile-label">Accuracy</span>
            </div>
          </div>

          <table className="data-table metrics-table">
            <tbody>
              <tr>
                <td>Confusion</td>
                <td className="mono-cell">
                  TP {metrics.true_positives} · FP {metrics.false_positives} · FN{" "}
                  {metrics.false_negatives} · TN {metrics.true_negatives}
                </td>
              </tr>
              <tr>
                <td>Coverage</td>
                <td className="mono-cell">
                  {pct(metrics.coverage)} ({metrics.committed}/{metrics.total_findings}{" "}
                  committed)
                </td>
              </tr>
              <tr>
                <td>Unknown rate</td>
                <td className="mono-cell">
                  {pct(metrics.unknown_rate)} ({metrics.unknown} abstentions)
                </td>
              </tr>
              <tr>
                <td>Facts scored</td>
                <td className="mono-cell">
                  {metrics.scored_facts} literal
                  {metrics.unscorable_facts > 0 &&
                    ` · ${metrics.unscorable_facts} excluded`}
                </td>
              </tr>
            </tbody>
          </table>
        </>
      )}

      <details className="metrics-method">
        <summary>Method and limitations</summary>
        <p className="text-muted">{metrics.method}</p>
        {metrics.limitations.length > 0 && (
          <ul>
            {metrics.limitations.map((l, i) => (
              <li key={i} className="text-muted">
                {l}
              </li>
            ))}
          </ul>
        )}
      </details>
    </div>
  );
}
