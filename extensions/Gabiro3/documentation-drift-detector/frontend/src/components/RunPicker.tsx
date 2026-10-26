import { Link } from "react-router-dom";
import { Icon } from "./Icon";
import { useRuns } from "../runs/RunContext";

export function RunPicker() {
  const { runs, selectedRunId, setSelectedRunId, refresh, loading } = useRuns();
  const selected = runs.find((r) => r.id === selectedRunId);

  return (
    <div className="run-picker-row">
      <select
        className="run-picker"
        value={selectedRunId ?? ""}
        onChange={(e) => setSelectedRunId(e.target.value || null)}
      >
        {runs.length === 0 && <option value="">No runs yet</option>}
        {runs.map((r) => (
          <option key={r.id} value={r.id}>
            {r.status === "failed" ? "! " : ""}
            {(r.corpus_ref || r.trigger || r.id).slice(0, 32)} · {r.id.slice(0, 8)} ·{" "}
            {r.status}
          </option>
        ))}
      </select>

      {selected && (
        <Link
          to={`/runs/${selected.id}/logs`}
          className="btn btn-ghost btn-icon"
          title="View logs for this run"
        >
          <Icon name="logs" size={15} />
        </Link>
      )}

      <button
        type="button"
        className="btn btn-ghost btn-icon"
        onClick={refresh}
        title="Refresh runs"
        disabled={loading}
      >
        <Icon name="refresh" size={15} />
      </button>
    </div>
  );
}