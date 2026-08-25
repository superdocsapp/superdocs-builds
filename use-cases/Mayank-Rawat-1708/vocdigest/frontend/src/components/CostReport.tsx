/**
 * @file src/components/CostReport.tsx
 * @description Per-stage and total cost display. Presented as an estimate rather than
 *   a bill, because token pricing is applied client-side from published rates.
 * @flow CostReport -> summary tiles + per-stage table
 * @dependencies lib/api types
 */
import type { CostReport as CostReportType } from "../lib/api";

export function CostReport({ report }: { report: CostReportType }) {
  const t = report.totals ?? { groq_tokens_used: 0, estimated_cost_usd: 0, superdocs_operations: 0, duration_seconds: 0 };
  const tiles = [
    { label: "Groq tokens", value: (t.groq_tokens_used ?? 0).toLocaleString() },
    { label: "Estimated cost", value: `$${(t.estimated_cost_usd ?? 0).toFixed(4)}` },
    { label: "SuperDocs ops", value: t.superdocs_operations ?? 0 },
    { label: "Total time", value: `${(t.duration_seconds ?? 0).toFixed(1)}s` },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {tiles.map((tile) => (
          <div key={tile.label} className="card p-4">
            <p className="text-xs text-slate-500">{tile.label}</p>
            <p className="text-xl font-semibold tabular-nums mt-1">{tile.value}</p>
          </div>
        ))}
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs uppercase text-slate-500">
            <tr>
              <th className="text-left px-4 py-2 font-medium">Stage</th>
              <th className="text-right px-4 py-2 font-medium">Duration</th>
              <th className="text-right px-4 py-2 font-medium">Tokens</th>
              <th className="text-right px-4 py-2 font-medium">Cost</th>
              <th className="text-right px-4 py-2 font-medium">SD ops</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {report.stages.map((s) => (
              <tr key={s.stage}>
                <td className="px-4 py-2">{s.stage}</td>
                <td className="px-4 py-2 text-right tabular-nums">{(s.duration_seconds ?? 0).toFixed(2)}s</td>
                <td className="px-4 py-2 text-right tabular-nums">{(s.groq_tokens_used ?? 0).toLocaleString()}</td>
                <td className="px-4 py-2 text-right tabular-nums">${(s.estimated_cost_usd ?? 0).toFixed(5)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{s.superdocs_operations ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-slate-500">
        Cost is estimated from published Groq token pricing, not a billed figure.
      </p>
    </div>
  );
}
