import type { CostStage } from "../api";

interface Props {
  stages: CostStage[];
  totalOps: number;
}

export function CostPanel({ stages, totalOps }: Props) {
  if (stages.length === 0) return null;

  return (
    <div className="cost-panel">
      <h2>Cost — {totalOps} total ops</h2>
      <table>
        <thead>
          <tr>
            <th>Stage</th>
            <th>Steps</th>
            <th>Tokens In</th>
            <th>Tokens Out</th>
            <th>Ops</th>
            <th>Time (ms)</th>
          </tr>
        </thead>
        <tbody>
          {stages.map((s, i) => (
            <tr key={i}>
              <td>{s.node}</td>
              <td>{s.steps}</td>
              <td>{s.total_tokens_in}</td>
              <td>{s.total_tokens_out}</td>
              <td>{s.total_superdocs_ops}</td>
              <td>{s.total_ms}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}