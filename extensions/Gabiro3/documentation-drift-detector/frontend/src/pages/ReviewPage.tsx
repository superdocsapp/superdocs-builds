import { useState, useEffect } from "react";
import type { Finding, CostStage, RunMetrics } from "../api";
import {
  getFindings,
  approveFinding,
  rejectFinding,
  getCost,
  getMetrics,
  applyApproved,
} from "../api";
import { FindingCard } from "../components/FindingCard";
import { UnknownPanel } from "../components/UnknownPanel";
import { CostPanel } from "../components/CostPanel";
import { MetricsPanel } from "../components/MetricsPanel";
import { Icon } from "../components/Icon";
import { RunPicker } from "../components/RunPicker";
import { useRuns } from "../runs/RunContext";
import { useNotifications } from "../notifications/NotificationContext";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function ReviewPage() {
  const { selectedRunId } = useRuns();
  const { notify } = useNotifications();
  const [findings, setFindings] = useState<Finding[]>([]);
  const [cost, setCost] = useState<CostStage[]>([]);
  const [totalOps, setTotalOps] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [metrics, setMetrics] = useState<RunMetrics | null>(null);
  const [applying, setApplying] = useState(false);

  const poll = () => {
    if (!selectedRunId) return;
    setLoading(true);
    Promise.all([
      getFindings(selectedRunId),
      getCost(selectedRunId),
      getMetrics(selectedRunId).catch(() => null),
    ])
      .then(([data, costData, metricsData]) => {
        setFindings(data.findings);
        setCost(costData.stages);
        setTotalOps(costData.total_ops);
        setMetrics(metricsData);
        setLoaded(true);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    setLoaded(false);
    if (selectedRunId) {
      poll();
      const interval = setInterval(poll, 3000);
      return () => clearInterval(interval);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId]);

  const handleApprove = async (id: string, feedback?: string) => {
    try {
      const res = await approveFinding(id, feedback);
      // Approving now schedules the edit. The toast reports what was actually
      // set in motion rather than promising an apply that used to never come.
      notify(
        "Finding approved",
        res.apply_status === "applied"
          ? "Already applied to the document."
          : "Applying the fix to the document now — this card will show the result.",
        "success"
      );
      poll();
    } catch (err) {
      notify("Approve failed", errorMessage(err), "error");
    }
  };

  const handleReject = async (id: string, feedback: string) => {
    try {
      await rejectFinding(id, feedback);
      notify("Finding rejected", feedback, "success");
      poll();
    } catch (err) {
      notify("Reject failed", errorMessage(err), "error");
    }
  };

  async function handleApplyAll() {
    if (!selectedRunId) return;
    setApplying(true);
    try {
      const res = await applyApproved(selectedRunId);
      const applied = res.counts["APPLIED"] ?? 0;
      const blocked =
        (res.counts["NEEDS_ESCALATION"] ?? 0) + (res.counts["ALARM"] ?? 0);
      if (blocked > 0) {
        // A blocked commit is the byte Judge doing its job — surface it loudly.
        notify(
          `${applied} applied, ${blocked} blocked`,
          "The byte Judge refused edits that strayed outside the approved chunk.",
          "error"
        );
      } else if (applied > 0) {
        notify(
          `${applied} fix${applied === 1 ? "" : "es"} applied`,
          "Every other chunk verified byte-identical.",
          "success"
        );
      } else {
        notify("Nothing to apply", "Every approved fix has already reached its document.", "info");
      }
      poll();
    } catch (err) {
      notify("Apply failed", errorMessage(err), "error");
    } finally {
      setApplying(false);
    }
  }

  const confirmed = findings.filter((f) => f.state === "CONFIRMED_DRIFT");
  const unknown = findings.filter((f) => f.state === "UNKNOWN");
  const noDrift = findings.filter((f) => f.state === "NO_DRIFT");

  return (
    <div className="page">
      <header className="page-header page-header-row">
        <div>
          <h1>Review</h1>
          <p className="page-subtitle">Findings, evidence, and cost for the selected run.</p>
        </div>
        <div className="review-header-right">
          <RunPicker />
          {totalOps > 0 && <span className="badge badge-neutral">Total: {totalOps} ops</span>}
          <button
            className="btn btn-primary"
            onClick={handleApplyAll}
            disabled={applying || !selectedRunId}
            title="Retry any approved fix that has not reached its document. Approving already applies automatically; this is the catch-up for edits that were blocked or failed."
          >
            <Icon name="check" size={14} /> {applying ? "Applying…" : "Retry unapplied"}
          </button>
        </div>
      </header>

      <section className="panel">
        <h2 className="section-title">Findings ({confirmed.length})</h2>
        {confirmed.length === 0 && noDrift.length === 0 && (
          <div className="empty-state">
            <p className="empty-state-title">
              {!selectedRunId ? "No run selected" : loading && !loaded ? "Loading..." : "No drift detected"}
            </p>
            {!selectedRunId && (
              <p className="text-muted">Upload documents on the Documents page to start a run.</p>
            )}
          </div>
        )}
        {confirmed.map((f) => (
          <FindingCard
            key={f.id}
            finding={f}
            onApprove={(fb?: string) => handleApprove(f.id, fb)}
            onReject={(fb: string) => handleReject(f.id, fb)}
          />
        ))}
      </section>

      <section className="panel">
        <MetricsPanel metrics={metrics} />
      </section>

      <section className="panel">
        <UnknownPanel items={unknown} />
      </section>

      <section className="panel">
        <CostPanel stages={cost} totalOps={totalOps} />
      </section>
    </div>
  );
}