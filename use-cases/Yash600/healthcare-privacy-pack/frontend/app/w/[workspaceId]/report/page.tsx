"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, ReportOut } from "@/lib/api";
import { IconFileText } from "../../../icons";

export default function ReportPage() {
  const params = useParams();
  const workspaceId = String(params.workspaceId);

  const [reports, setReports] = useState<ReportOut[]>([]);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const rpts = await api.listReports(workspaceId);
      setReports(rpts);
    } catch (e) {
      setError(String(e));
    }
  }, [workspaceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const generate = async () => {
    setGenerating(true);
    setError(null);
    try {
      await api.generateReport(workspaceId);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setGenerating(false);
    }
  };

  const latest = reports[0];

  return (
    <div style={{ maxWidth: 760 }}>
      <div className="eyebrow"><IconFileText size={13} /> Report</div>
      <h1>Report</h1>
      <p className="lede">
        A report only ever reflects approved, active versions -- a proposed change that hasn't been
        approved yet can never end up in a report by accident.
      </p>

      {error && <div className="error-banner">{error}</div>}

      <div className="card glass-strong">
        <div className="row between">
          <h3 style={{ margin: 0 }}>Latest report</h3>
          <button className="btn" onClick={generate} disabled={generating}>
            {generating ? "Generating..." : "Generate report"}
          </button>
        </div>
        {!latest && <div className="empty">No report generated yet.</div>}
        {latest && (
          <div className="col" style={{ marginTop: 12, gap: 6, fontSize: 13.5 }}>
            <div className="row between"><span className="muted">Pack version</span><span>{latest.pack_version_label}</span></div>
            <div className="row between"><span className="muted">Documents</span><span>{latest.summary.documents} ({latest.summary.policies} policies, {latest.summary.procedures} procedures)</span></div>
            <div className="row between"><span className="muted">References</span><span>{latest.summary.references} ({latest.summary.references_valid} valid, {latest.summary.references_stale} stale, {latest.summary.references_needs_review} needs review)</span></div>
            <div className="row between"><span className="muted">Open findings</span><span>{latest.summary.findings_open}</span></div>
            <div className="row between"><span className="muted">Pending reviews</span><span>{latest.summary.pending_reviews}</span></div>
            <div className="row between">
              <span className="muted">Validation</span>
              <span className={`badge ${latest.summary.validation_overall_status === "pass" ? "synced" : "stale"}`}>
                {latest.summary.validation_overall_status}
              </span>
            </div>
          </div>
        )}
      </div>

      {reports.length > 1 && (
        <div className="card glass-strong">
          <h3>History</h3>
          <div className="col" style={{ gap: 6 }}>
            {reports.map((r) => (
              <div key={r.id} className="row between" style={{ fontSize: 13 }}>
                <span>{r.pack_version_label}</span>
                <span className="faint">{new Date(r.generated_at).toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
