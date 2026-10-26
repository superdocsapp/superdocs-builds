import { useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  getRunLogs,
  resumeRun,
  stopRun,
  type RunLogs,
  type TraceEntry,
} from "../api";
import { Icon } from "../components/Icon";
import { useNotifications } from "../notifications/NotificationContext";
import { isRunActive } from "../runs/RunActivityContext";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function stamp(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "--:--:--";
  return d.toLocaleTimeString("en-GB", { hour12: false });
}

/** Colour-code by what the node decided, so a skim finds the interesting
 *  lines: abstentions, failures, and checkpoint skips. */
function toneFor(entry: TraceEntry): string {
  const d = (entry.decision || "").toLowerCase();
  if (d.startsWith("failed") || d.includes("alarm")) return "err";
  if (d.includes("cancel")) return "warn";
  if (d.includes("skipped")) return "dim";
  if (d.includes("unknown")) return "warn";
  if (d.includes("confirmed_drift")) return "ok";
  return "";
}

function LogLine({ entry }: { entry: TraceEntry }) {
  const tone = toneFor(entry);
  const meta: string[] = [];
  if (entry.ms) meta.push(`${entry.ms}ms`);
  if (entry.tokens_in || entry.tokens_out)
    meta.push(`${entry.tokens_in ?? 0}/${entry.tokens_out ?? 0} tok`);
  if (entry.superdocs_ops) meta.push(`${entry.superdocs_ops} ops`);

  const evidence =
    entry.evidence && Object.keys(entry.evidence).length > 0
      ? JSON.stringify(entry.evidence)
      : "";

  return (
    <div className={`term-line${tone ? ` term-${tone}` : ""}`}>
      <span className="term-ts">{stamp(entry.ts)}</span>
      <span className="term-node">{entry.node}</span>
      <span className="term-decision">{entry.decision ?? ""}</span>
      {evidence && <span className="term-evidence">{evidence}</span>}
      {meta.length > 0 && <span className="term-meta">{meta.join(" · ")}</span>}
    </div>
  );
}

export function RunLogsPage() {
  const { runId = "" } = useParams();
  const { notify } = useNotifications();
  const [logs, setLogs] = useState<RunLogs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [follow, setFollow] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const active = logs ? isRunActive(logs.run.status) : false;

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;

    const load = () =>
      getRunLogs(runId)
        .then((data) => {
          if (!cancelled) {
            setLogs(data);
            setError(null);
          }
        })
        .catch((err) => {
          if (!cancelled) setError(errorMessage(err));
        });

    load();
    // Follow live while the run is still moving; stop polling once terminal.
    const interval = setInterval(() => {
      if (!cancelled) load();
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [runId]);

  useEffect(() => {
    if (follow) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [logs, follow]);

  async function handleStop() {
    setBusy(true);
    try {
      await stopRun(runId);
      notify("Stop requested", "Finishing the current step, then halting.", "info");
    } catch (err) {
      notify("Stop failed", errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleResume() {
    setBusy(true);
    try {
      const res = await resumeRun(runId);
      notify(
        "Run resumed",
        `Skipping ${res.resumed_from_completed_steps} completed step${
          res.resumed_from_completed_steps === 1 ? "" : "s"
        }.`,
        "success"
      );
    } catch (err) {
      notify("Resume failed", errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  }

  const completedSteps = logs?.steps.filter((s) => s.status === "completed").length ?? 0;

  return (
    <div className="page">
      <header className="page-header page-header-row">
        <div>
          <div className="breadcrumb">
            <Link to="/">Review</Link>
            <span className="text-muted"> / </span>
            <span className="text-muted">Logs</span>
          </div>
          <h1>Run {runId.slice(0, 8)}</h1>
          <p className="page-subtitle">
            {logs ? (
              <>
                {logs.run.corpus_ref || logs.run.trigger} ·{" "}
                <span className={`run-status run-status-${logs.run.status}`}>
                  {logs.run.status}
                </span>{" "}
                · {completedSteps} checkpointed step{completedSteps === 1 ? "" : "s"}
              </>
            ) : (
              "Loading…"
            )}
          </p>
        </div>

        <div className="review-header-right">
          <label className="follow-toggle">
            <input
              type="checkbox"
              checked={follow}
              onChange={(e) => setFollow(e.target.checked)}
            />
            Follow
          </label>
          {active ? (
            <button className="btn btn-danger" onClick={handleStop} disabled={busy}>
              <Icon name="close" size={14} /> Stop
            </button>
          ) : (
            <button className="btn btn-primary" onClick={handleResume} disabled={busy}>
              <Icon name="refresh" size={14} /> Resume
            </button>
          )}
        </div>
      </header>

      {error && <p className="text-danger">{error}</p>}

      <div className="terminal">
        {logs && logs.trace.length === 0 && (
          <div className="term-line term-dim">
            <span className="term-decision">No trace entries yet…</span>
          </div>
        )}
        {logs?.trace.map((entry) => (
          <LogLine key={entry.id} entry={entry} />
        ))}
        {active && (
          <div className="term-line term-dim">
            <span className="term-ts">{stamp(new Date().toISOString())}</span>
            <span className="term-cursor">▋</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {logs && logs.steps.length > 0 && (
        <section className="panel">
          <h2 className="section-title">Checkpoints</h2>
          <p className="subtitle">
            Completed steps are skipped on resume — this is what makes a restart
            cheap instead of starting from scratch.
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Node</th>
                <th>Status</th>
                <th>Started</th>
                <th>Ended</th>
              </tr>
            </thead>
            <tbody>
              {logs.steps.map((s, i) => (
                <tr key={`${s.node}-${s.input_hash}-${i}`}>
                  <td>{s.node}</td>
                  <td>
                    <span
                      className={`badge ${
                        s.status === "completed" ? "badge-success" : "badge-neutral"
                      }`}
                    >
                      {s.status}
                    </span>
                  </td>
                  <td className="mono-cell">{s.started_at ? stamp(s.started_at) : "—"}</td>
                  <td className="mono-cell">{s.ended_at ? stamp(s.ended_at) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
