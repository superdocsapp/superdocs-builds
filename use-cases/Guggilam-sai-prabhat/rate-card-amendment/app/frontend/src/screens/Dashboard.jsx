import { useEffect, useState } from "react";
import { listCases, proposeCase } from "../api.js";
import StateBadge from "../components/StateBadge.jsx";
import FailureBanner from "../components/FailureBanner.jsx";

export default function Dashboard({ run, onOpenReview }) {
  const [cases, setCases] = useState(run.cases);
  const [proposing, setProposing] = useState(null);
  const [failure, setFailure] = useState(null);

  useEffect(() => {
    refresh();
  }, [run.run_id]);

  async function refresh() {
    const fresh = await listCases(run.run_id);
    setCases(fresh);
  }

  async function handlePropose(caseId) {
    setFailure(null);
    setProposing(caseId);
    try {
      await proposeCase(run.run_id, caseId);
      await refresh();
    } catch (error) {
      setFailure(error.detail || { what: error.message, likely_cause: "unknown", next_action: "retry" });
    } finally {
      setProposing(null);
    }
  }

  return (
    <div className="screen">
      <h1>2. Analysis Dashboard</h1>
      <p className="subtitle">
        Run {run.run_id.slice(0, 8)} — {run.dry_run ? "dry run (no SuperDocs calls made)" : "live"} — proposed effective date {run.proposed_effective_date}
      </p>
      <FailureBanner failure={failure} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Partner</th>
              <th>Current → Proposed Rates</th>
              <th>Pricing Clause</th>
              <th>Citation</th>
              <th>Notice Period</th>
              <th>State</th>
              <th>Blocking Reason</th>
              <th>Confidence</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr key={c.case_id}>
                <td>
                  <div className="partner-name">{c.partner_name || "(unknown)"}</div>
                  <div className="muted">{c.contract_identifier}</div>
                </td>
                <td>
                  <ul className="rate-list">
                    {c.proposed_rate_changes.slice(0, 3).map((r) => (
                      <li key={r.destination}>
                        {r.destination}: {r.old_rate_usd_per_min ?? "—"} → {r.new_rate_usd_per_min ?? "—"}{" "}
                        {r.change_pct != null && (
                          <span className={r.change_pct >= 0 ? "up" : "down"}>({r.change_pct}%)</span>
                        )}
                      </li>
                    ))}
                    {c.proposed_rate_changes.length > 3 && (
                      <li className="muted">+{c.proposed_rate_changes.length - 3} more</li>
                    )}
                  </ul>
                </td>
                <td className="muted small">{c.pricing_clause_reference || "—"}</td>
                <td className="muted small citation">{c.pricing_clause_citation || "—"}</td>
                <td>
                  {c.notice_period_days != null ? `${c.notice_period_days} days` : c.notice_period_type || "—"}
                </td>
                <td>
                  <StateBadge state={c.state} />
                  {c.requires_human_escalation && <div className="tag warn">escalation</div>}
                  {c.prompt_injection_present && <div className="tag warn">injection detected</div>}
                </td>
                <td className="small">{c.blocking_reason || "—"}</td>
                <td>{(c.confidence * 100).toFixed(0)}%</td>
                <td>
                  {c.state === "analysing" && !run.dry_run && (
                    <button disabled={proposing === c.case_id} onClick={() => handlePropose(c.case_id)}>
                      {proposing === c.case_id ? "Proposing…" : "Propose"}
                    </button>
                  )}
                  {["proposed", "partially_approved", "approved", "exported"].includes(c.state) && (
                    <button onClick={() => onOpenReview(c.case_id)}>Review</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
