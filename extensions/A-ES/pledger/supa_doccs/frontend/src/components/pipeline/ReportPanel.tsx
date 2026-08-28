/**
 * Compliance Report Panel — per-run report with real data.
 *
 * Only opens via explicit user action (click "Report" button).
 * Always tied to a specific run_id. Fetches:
 *   - GET /runs/{id}/report — pipeline results (claims, findings, routing, cost)
 *   - GET /approval/runs/{id}/queue — live approval queue status
 *
 * Sections: Header, Summary, Claims, Findings/Escalated Items, Actions.
 */
import { useState, useEffect } from 'react';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ReportData {
  run_id: string;
  ready: boolean;
  status: string;
  generated_at: string;
  document: {
    filename: string | null;
    classification: string;
    classification_confidence: number;
    text_length: number;
  };
  assessment: {
    overall_verdict: string;
    risk_level: string;
    risk_score: number;
    summary: string;
  };
  claims: {
    total: number;
    compliant: number;
    non_compliant: number;
    indeterminate: number;
    details: Array<{
      claim_id: string;
      claim_text: string;
      confidence: number;
      verdict: string;
      rule_id: string | null;
      needs_review: boolean;
    }>;
  };
  findings: {
    total: number;
    items: Array<Record<string, any>>;
    source_findings: Array<Record<string, any>>;
  };
  routing: {
    auto_approved: number;
    escalated: number;
    auto_rejected: number;
  };
  execution: {
    total_duration_ms: number;
    total_cost_usd: number;
    total_input_tokens: number;
    total_output_tokens: number;
    nodes_completed: number;
    nodes_skipped: number;
    nodes_failed: number;
  };
}

interface ApprovalItem {
  id: string;
  run_id: string;
  item_type: string;
  payload: Record<string, any>;
  status: string;
  queued_at: string;
  decided_at: string | null;
  decision: string | null;
  reviewer_id: string | null;
}

interface ApprovalQueueData {
  run_id: string;
  items: ApprovalItem[];
  total: number;
  pending: number;
}

interface ReportPanelProps {
  runId: string | null;
  runStatus: string | null;
  onClose: () => void;
  open: boolean;
  /** Callback to open the approval panel for this run */
  onOpenApprovals?: () => void;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const VERDICT_STYLES: Record<string, string> = {
  'COMPLIANT': 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  'MOSTLY COMPLIANT': 'bg-emerald-500/15 text-emerald-200 border-emerald-500/25',
  'REQUIRES REVIEW': 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  'NON-COMPLIANT': 'bg-rose-500/20 text-rose-300 border-rose-500/30',
};

const RISK_COLORS: Record<string, string> = {
  'MINIMAL': 'text-emerald-400',
  'LOW': 'text-emerald-300',
  'MEDIUM': 'text-amber-300',
  'HIGH': 'text-rose-400',
};

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ReportPanel({ runId, runStatus, onClose, open, onOpenApprovals }: ReportPanelProps) {
  const [report, setReport] = useState<ReportData | null>(null);
  const [approvals, setApprovals] = useState<ApprovalQueueData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch report + approval data when opened (or runId changes while open)
  useEffect(() => {
    if (!open || !runId) {
      return;
    }

    setLoading(true);
    setError(null);

    const fetchAll = async () => {
      try {
        const [reportRes, approvalRes] = await Promise.all([
          fetch(`${BASE_URL}/runs/${runId}/report`),
          fetch(`${BASE_URL}/approval/runs/${runId}/queue`),
        ]);

        if (reportRes.ok) {
          const data = await reportRes.json();
          setReport(data.ready ? data : null);
        } else {
          setReport(null);
          setError('Failed to load report data');
        }

        let approvalData: ApprovalQueueData | null = null;
        if (approvalRes.ok) {
          approvalData = await approvalRes.json();
        }

        // If there are escalated claims but no approval items, backfill the queue
        if (approvalData && approvalData.total === 0) {
          try {
            const backfillRes = await fetch(`${BASE_URL}/runs/${runId}/populate-queue`, { method: 'POST' });
            if (backfillRes.ok) {
              const backfillData = await backfillRes.json();
              if (backfillData.created > 0) {
                // Re-fetch approval queue after backfill
                const refetchRes = await fetch(`${BASE_URL}/approval/runs/${runId}/queue`);
                if (refetchRes.ok) {
                  approvalData = await refetchRes.json();
                }
              }
            }
          } catch { /* backfill is best-effort */ }
        }

        setApprovals(approvalData);
      } catch {
        setError('Network error loading report');
      } finally {
        setLoading(false);
      }
    };

    fetchAll();
  }, [open, runId]);

  if (!open) return null;

  // Handle inline approve/reject decisions
  const handleDecision = async (itemId: string, decision: 'approved' | 'rejected') => {
    try {
      await fetch(`${BASE_URL}/approval/items/${itemId}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, reviewer_id: 'report-user', justification: `${decision} via compliance report` }),
      });
      // Update local state
      setApprovals((prev) => {
        if (!prev) return prev;
        const updatedItems = prev.items.map((item) =>
          item.id === itemId ? { ...item, status: decision, decision, decided_at: new Date().toISOString() } : item
        );
        const pendingNow = updatedItems.filter((i) => i.status === 'pending').length;
        return { ...prev, items: updatedItems, pending: pendingNow };
      });
    } catch { /* keep original state on failure */ }
  };

  const shortRunId = runId?.slice(0, 8) ?? '—';
  const filename = report?.document?.filename ?? '—';
  const pendingCount = approvals?.pending ?? 0;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 z-30 backdrop-blur-sm" onClick={onClose} />

      {/* Panel */}
      <div className="fixed inset-x-0 bottom-0 z-40 max-h-[85vh] bg-[#0c0f1a] border-t border-white/[0.08] rounded-t-2xl shadow-2xl shadow-black/50 overflow-hidden flex flex-col">
        {/* ─── Header ─────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06] bg-[#0f1320]/80 sticky top-0 z-10">
          <div className="flex items-center gap-3 min-w-0">
            <svg className="w-5 h-5 text-indigo-400 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
              <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-white/90 truncate">
                Compliance Report — Run {shortRunId}
              </h2>
              <p className="text-[11px] text-white/40 truncate">
                {filename} {report?.document?.classification ? `· ${report.document.classification.replace(/_/g, ' ')}` : ''}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-white/40 hover:text-white/70 hover:bg-white/[0.05] transition-colors flex-shrink-0">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* ─── Content ────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading && (
            <div className="flex items-center justify-center py-20">
              <svg className="w-6 h-6 text-indigo-400 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <circle cx="12" cy="12" r="10" opacity={0.25} />
                <path d="M4 12a8 8 0 018-8" opacity={0.75} />
              </svg>
              <span className="ml-3 text-sm text-white/50">Loading report...</span>
            </div>
          )}

          {error && !loading && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <p className="text-sm text-rose-300/70">{error}</p>
              <p className="text-xs text-white/30 mt-2">Run ID: {runId}</p>
            </div>
          )}

          {!loading && !error && report && (
            <div className="max-w-4xl mx-auto space-y-6">

              {/* ─── 1. Run Metadata Header ────────────────────────────── */}
              <div className="rounded-xl border border-white/[0.08] bg-gradient-to-br from-[#141927] to-[#0f1320] p-5">
                <div className="flex items-start justify-between">
                  <div className="space-y-2">
                    <span className={`inline-flex items-center rounded-lg px-3 py-1.5 text-sm font-bold border ${VERDICT_STYLES[report.assessment.overall_verdict] ?? 'bg-white/10 text-white/60 border-white/20'}`}>
                      {report.assessment.overall_verdict}
                    </span>
                    <p className="text-sm text-white/60 leading-relaxed max-w-xl">
                      {report.assessment.summary}
                    </p>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-white/35 pt-1">
                      <span>Run: <span className="font-mono text-white/50">{shortRunId}</span></span>
                      <span>Status: <span className="text-white/50">{runStatus ?? report.status}</span></span>
                      {report.generated_at && <span>Generated: {new Date(report.generated_at).toLocaleString()}</span>}
                      <span>Text: {report.document.text_length.toLocaleString()} chars</span>
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0 ml-4">
                    <div className="text-[10px] uppercase tracking-wider text-white/30 mb-1">Risk Score</div>
                    <div className={`text-3xl font-bold ${RISK_COLORS[report.assessment.risk_level] ?? 'text-white/60'}`}>
                      {report.assessment.risk_score}
                    </div>
                    <div className={`text-xs font-medium ${RISK_COLORS[report.assessment.risk_level] ?? 'text-white/40'}`}>
                      {report.assessment.risk_level}
                    </div>
                  </div>
                </div>
              </div>

              {/* ─── 2. Summary Numbers ────────────────────────────────── */}
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
                <StatCard label="Claims" value={report.claims.total} />
                <StatCard label="Compliant" value={report.claims.compliant} color="text-emerald-400" />
                <StatCard label="Non-Compliant" value={report.claims.non_compliant} color="text-rose-400" />
                <StatCard label="Needs Review" value={report.claims.indeterminate} color="text-amber-400" />
                <StatCard label="Findings" value={report.findings.total + report.findings.source_findings.length} color="text-violet-400" />
                <StatCard label="Pending Approvals" value={pendingCount} color={pendingCount > 0 ? 'text-amber-400' : 'text-white/50'} />
              </div>

              {/* Execution cost bar */}
              <div className="flex flex-wrap items-center gap-4 px-4 py-2.5 rounded-lg border border-white/[0.06] bg-[#141927]/40 text-[11px]">
                <span className="text-white/30">Duration: <span className="font-mono text-white/60">{formatDuration(report.execution.total_duration_ms)}</span></span>
                <span className="text-white/30">Cost: <span className="font-mono text-violet-300/70">${report.execution.total_cost_usd.toFixed(4)}</span></span>
                <span className="text-white/30">Tokens: <span className="font-mono text-white/50">{(report.execution.total_input_tokens + report.execution.total_output_tokens).toLocaleString()}</span></span>
                <span className="text-white/30">Nodes: <span className="font-mono text-white/50">{report.execution.nodes_completed} completed, {report.execution.nodes_skipped} skipped</span></span>
                <span className="text-white/30">Escalated: <span className="font-mono text-amber-300/70">{report.routing.escalated}</span></span>
              </div>

              {/* ─── 3. Claim-by-Claim Section ─────────────────────────── */}
              <div className="rounded-xl border border-white/[0.08] bg-[#141927]/60 p-4">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-white/40 mb-3">
                  Claim-by-Claim Analysis ({report.claims.total})
                </h3>
                <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
                  {report.claims.details.map((claim) => (
                    <ClaimRow key={claim.claim_id} claim={claim} pendingItems={approvals?.items} />
                  ))}
                  {report.claims.details.length === 0 && (
                    <p className="text-xs text-white/30 text-center py-4">No claims extracted</p>
                  )}
                </div>
              </div>

              {/* ─── 4. Findings / Escalated Items ─────────────────────── */}
              {(approvals?.items?.length ?? 0) > 0 && (
                <div className="rounded-xl border border-white/[0.08] bg-[#141927]/60 p-4">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-white/40 mb-3">
                    Escalated Items — Approval Queue ({approvals!.total})
                  </h3>
                  <div className="grid grid-cols-4 gap-2 mb-3">
                    <MiniStat label="Pending" value={approvals!.pending} color="text-amber-400" />
                    <MiniStat label="Approved" value={approvals!.items.filter(i => i.status === 'approved').length} color="text-emerald-400" />
                    <MiniStat label="Rejected" value={approvals!.items.filter(i => i.status === 'rejected').length} color="text-rose-400" />
                    <MiniStat label="Needs recheck" value={approvals!.items.filter(i => i.status === 'approved_needs_recheck').length} color="text-amber-300" />
                  </div>
                  <div className="space-y-1.5 max-h-[250px] overflow-y-auto">
                    {approvals!.items.map((item) => (
                      <ApprovalItemRow key={item.id} item={item} onDecide={handleDecision} />
                    ))}
                  </div>
                </div>
              )}

              {/* Findings from pipeline (non-approval) */}
              {(report.findings.total > 0 || report.findings.source_findings.length > 0) && (
                <div className="rounded-xl border border-white/[0.08] bg-[#141927]/60 p-4">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-white/40 mb-3">
                    Pipeline Findings ({report.findings.total + report.findings.source_findings.length})
                  </h3>
                  <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
                    {report.findings.items.map((f, i) => (
                      <FindingRow key={i} finding={f} />
                    ))}
                    {report.findings.source_findings.map((f, i) => (
                      <FindingRow key={`src-${i}`} finding={f} />
                    ))}
                  </div>
                </div>
              )}

              {/* ─── 5. Actions ────────────────────────────────────────── */}
              <div className="flex items-center gap-3 pt-2 pb-4">
                {pendingCount > 0 && onOpenApprovals && (
                  <button
                    onClick={() => { onClose(); onOpenApprovals(); }}
                    className="flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30 hover:bg-amber-500/25 transition-colors"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                      <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Go to Pending Approvals ({pendingCount})
                  </button>
                )}
                <button
                  onClick={onClose}
                  className="rounded-lg px-4 py-2.5 text-sm font-medium text-white/50 border border-white/[0.08] hover:bg-white/[0.04] hover:text-white/70 transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          )}

          {/* No report data but not loading/error (run hasn't completed) */}
          {!loading && !error && !report && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <p className="text-sm text-white/40">No report available for this run yet.</p>
              <p className="text-xs text-white/25 mt-1">Reports are generated when a pipeline run completes.</p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-[#141927]/60 p-3 text-center">
      <div className={`text-xl font-bold ${color ?? 'text-white/80'}`}>{value}</div>
      <div className="text-[10px] text-white/30 uppercase tracking-wider mt-0.5">{label}</div>
    </div>
  );
}

function MiniStat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="rounded-md bg-[#0a0d16]/60 border border-white/[0.04] py-1.5 text-center">
      <div className={`text-base font-bold ${color ?? 'text-white/60'}`}>{value}</div>
      <div className="text-[9px] text-white/25 uppercase">{label}</div>
    </div>
  );
}

function ClaimRow({ claim, pendingItems }: {
  claim: { claim_id: string; claim_text: string; confidence: number; verdict: string; rule_id: string | null; needs_review: boolean };
  pendingItems?: ApprovalItem[];
}) {
  // Check if this claim has a pending approval item
  const pendingItem = pendingItems?.find(
    (item) => item.status === 'pending' && (
      item.payload?.details?.claim_id === claim.claim_id ||
      item.payload?.summary === claim.claim_text
    )
  );

  const verdictStyles: Record<string, string> = {
    compliant: 'bg-emerald-500/20 text-emerald-300',
    non_compliant: 'bg-rose-500/20 text-rose-300',
    indeterminate: 'bg-amber-500/20 text-amber-300',
  };

  const verdictIcon: Record<string, string> = {
    compliant: '\u2713',
    non_compliant: '\u2717',
  };

  return (
    <div className="flex items-start gap-3 px-3 py-2 rounded-lg bg-[#0a0d16]/60 border border-white/[0.03]">
      <span className={`flex-shrink-0 inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold ${verdictStyles[claim.verdict] ?? 'bg-white/10 text-white/40'}`}>
        {verdictIcon[claim.verdict] ?? '?'}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-[12px] text-white/70 leading-snug">{claim.claim_text}</p>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className="text-[10px] font-mono text-white/25">{claim.claim_id}</span>
          {claim.rule_id && (
            <span className="text-[10px] text-indigo-300/50">{claim.rule_id}</span>
          )}
          {claim.needs_review && (
            <span className="text-[9px] px-1 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">REVIEW</span>
          )}
          {pendingItem && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/25 animate-pulse">
              pending approval
            </span>
          )}
        </div>
      </div>
      <span className="text-[10px] text-white/30 font-mono flex-shrink-0">
        {(claim.confidence * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function ApprovalItemRow({ item, onDecide }: { item: ApprovalItem; onDecide?: (itemId: string, decision: 'approved' | 'rejected') => void }) {
  const [submitting, setSubmitting] = useState<string | null>(null);
  const statusStyles: Record<string, string> = {
    pending: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    approved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    rejected: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  };

  const summary = item.payload?.summary ?? item.payload?.claim_text ?? item.id.slice(0, 12);

  const handleDecide = async (decision: 'approved' | 'rejected') => {
    setSubmitting(decision);
    if (onDecide) await onDecide(item.id, decision);
    setSubmitting(null);
  };

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#0a0d16]/60 border border-white/[0.03]">
      <span className={`flex-shrink-0 inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider border ${statusStyles[item.status] ?? statusStyles.pending}`}>
        {item.status}
      </span>
      <p className="flex-1 text-[11px] text-white/60 truncate">{summary}</p>
      {item.status === 'pending' && onDecide && (
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={() => handleDecide('approved')}
            disabled={submitting !== null}
            className="px-1.5 py-0.5 rounded text-[9px] font-medium text-emerald-300 hover:bg-emerald-500/15 border border-emerald-500/20 transition-colors disabled:opacity-40"
          >
            {submitting === 'approved' ? '...' : 'Approve'}
          </button>
          <button
            onClick={() => handleDecide('rejected')}
            disabled={submitting !== null}
            className="px-1.5 py-0.5 rounded text-[9px] font-medium text-rose-300 hover:bg-rose-500/15 border border-rose-500/20 transition-colors disabled:opacity-40"
          >
            {submitting === 'rejected' ? '...' : 'Reject'}
          </button>
        </div>
      )}
      {item.status !== 'pending' && (
        <span className="text-[9px] text-white/20 font-mono flex-shrink-0">{item.item_type}</span>
      )}
    </div>
  );
}

function FindingRow({ finding }: { finding: Record<string, any> }) {
  const severity = finding.severity ?? 'medium';
  const sevColors: Record<string, string> = {
    high: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
    medium: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
    low: 'bg-white/10 text-white/50 border-white/20',
  };

  return (
    <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-[#0a0d16]/60 border border-white/[0.03]">
      <span className={`flex-shrink-0 inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-bold uppercase border ${sevColors[severity] ?? sevColors.medium}`}>
        {severity}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-[12px] text-white/60 leading-snug truncate">
          {finding.description || finding.reason || finding.finding_type || '—'}
        </p>
        {finding.rule_id && (
          <span className="text-[10px] text-indigo-300/50">{finding.rule_id}</span>
        )}
      </div>
    </div>
  );
}

export default ReportPanel;
