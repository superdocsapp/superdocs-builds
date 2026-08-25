/**
 * @file src/pages/Dashboard.tsx
 * @description Run overview. Lists every run with its status and routes the user to
 *   whichever screen is actually useful next — the approval gate when the run is
 *   waiting on a human, the digest when it is done.
 * @flow mount -> fetch runs -> poll every 5s while any run is active
 * @dependencies lib/api, RunStatusBadge
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, FileCheck2, Inbox, Loader2 } from "lucide-react";
import { api, type RunSummary } from "../lib/api";
import { RunStatusBadge } from "../components/RunStatusBadge";

const ACTIVE = new Set(["PENDING","INGESTING","CLASSIFYING","EXTRACTING","THEMING","ANONYMIZING","COMPARING","DRAFTING","UPLOADING"]);

export default function Dashboard() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const data = await api.listRuns();
        if (alive) { setRuns(data); setError(null); }
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    void load();
    // Poll only matters while something is moving; the interval is cheap either way.
    const id = window.setInterval(load, 5000);
    return () => { alive = false; window.clearInterval(id); };
  }, []);

  if (error) return (
    <div className="card p-6 flex items-center gap-3 text-red-600">
      <AlertCircle className="w-5 h-5" /> {error}
    </div>
  );

  if (!runs) return (
    <div className="flex items-center gap-2 text-slate-500">
      <Loader2 className="w-4 h-4 animate-spin" /> Loading runs…
    </div>
  );

  if (runs.length === 0) return (
    <div className="card p-12 text-center">
      <Inbox className="w-10 h-10 mx-auto text-slate-300" />
      <h2 className="mt-4 font-semibold">No runs yet</h2>
      <p className="mt-1 text-sm text-slate-500">Upload a quarter of support conversations to generate your first digest.</p>
      <Link to="/upload" className="btn-primary mt-6">Start a run</Link>
    </div>
  );

  const activeRuns = runs.filter((r) => ACTIVE.has(r.status));

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Runs</h1>

      {activeRuns.length > 1 && (
        <div className="card p-4 text-sm border-amber-300">
          <strong>{activeRuns.length} runs are active.</strong> They all draw on the same
          provider token allowance, so one can exhaust it and make the others appear to
          fail for no visible reason. Cancel anything you no longer need.
        </div>
      )}
      <div className="space-y-2">
        {runs.map((run) => {
          const needsReview = run.status === "AWAITING_APPROVAL";
          const target = needsReview
            ? `/runs/${run.id}/approve`
            : run.status === "COMPLETE" ? `/runs/${run.id}/digest` : `/runs/${run.id}`;
          return (
            <Link key={run.id} to={target} className="card p-4 flex items-center gap-4 hover:border-accent transition block">
              <div className="flex-1 min-w-0">
                <p className="font-medium">{run.quarter_label} digest</p>
                <p className="text-xs text-slate-500 font-mono truncate">{run.id}</p>
                {run.error_message && (
                  <p className="text-xs text-red-600 mt-1 truncate">{run.error_message}</p>
                )}
              </div>
              {ACTIVE.has(run.status) && run.current_stage && (
                <span className="text-xs text-slate-500">{run.current_stage}</span>
              )}
              {needsReview && (
                <span className="text-xs font-medium text-amber-700 dark:text-amber-300">
                  {run.pending_approvals} to review
                </span>
              )}
              {run.export_available && <FileCheck2 className="w-4 h-4 text-emerald-600" />}
              <RunStatusBadge status={run.status} />
            </Link>
          );
        })}
      </div>
    </div>
  );
}