import { Link } from "react-router-dom";
import { Icon } from "./Icon";
import { useRunActivity } from "../runs/RunActivityContext";

function elapsedSince(iso: string): string {
  const started = new Date(iso).getTime();
  if (Number.isNaN(started)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function ActiveRunsPanel() {
  const { activeRuns, panelCollapsed, togglePanel } = useRunActivity();

  if (activeRuns.length === 0) return null;

  return (
    <aside
      className={`active-runs-panel${panelCollapsed ? " active-runs-panel-collapsed" : ""}`}
    >
      <button type="button" className="active-runs-header" onClick={togglePanel}>
        <span className="active-runs-header-left">
          <span className="spinner" aria-hidden="true" />
          Analyzing
          <span className="badge badge-neutral active-runs-count">{activeRuns.length}</span>
        </span>
        <Icon name={panelCollapsed ? "chevron-up" : "chevron-down"} size={15} />
      </button>

      {!panelCollapsed && (
        <ul className="active-runs-list">
          {activeRuns.map((run) => (
            <li key={run.id}>
              <Link
                to={`/runs/${run.id}/logs`}
                className="active-runs-item"
                title="View full logs for this run"
              >
                <span className="active-runs-pending-dot" aria-hidden="true" />
                <div className="active-runs-item-body">
                  <p className="active-runs-item-title">
                    {run.corpus_ref || run.trigger || "Run"}
                  </p>
                  <p className="active-runs-item-meta text-muted">
                    {run.status === "pending" ? "Queued" : "Processing"} ·{" "}
                    {elapsedSince(run.created_at)} · {run.id.slice(0, 8)}
                  </p>
                </div>
                <Icon name="chevron-right" size={14} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
