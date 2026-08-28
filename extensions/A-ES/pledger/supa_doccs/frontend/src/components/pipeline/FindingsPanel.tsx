/**
 * Findings Panel — the Phase 1 audit-trail requirement made visible.
 *
 * Lists EVERY finding ever generated for this run, resolved or not:
 * rule triggered, playbook, evaluation_method, citations, and current
 * status with who decided and when. Data comes from the audit trail
 * (audit_events) joined with approval_queue/decisions via
 * GET /runs/{id}/findings — never reconstructed client-side.
 */
import { useState, useEffect } from 'react';
import { fetchRunFindings, type RunFindings, type FindingRecord } from '@/services/pipelineApi';

interface FindingsPanelProps {
  runId: string | null;
  open: boolean;
  onClose: () => void;
}

const STATUS_CONFIG: Record<string, { label: string; badge: string }> = {
  pending: { label: 'Pending', badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  approved: { label: 'Approved', badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  rejected: { label: 'Rejected', badge: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  approved_needs_recheck: {
    label: 'Approved — needs recheck',
    badge: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  },
  unqueued: { label: 'Never escalated', badge: 'bg-white/[0.05] text-white/40 border-white/[0.1]' },
};

const SEV_COLORS: Record<string, string> = {
  high: 'text-rose-300 bg-rose-500/15',
  medium: 'text-amber-300 bg-amber-500/15',
  low: 'text-white/50 bg-white/[0.06]',
};

function CitationChips({ finding }: { finding: FindingRecord }) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  if (finding.citations.length === 0) {
    return (
      <span className="inline-flex items-center rounded px-1.5 py-px text-[9px] font-bold uppercase tracking-wider bg-rose-500/10 text-rose-300/70 border border-rose-500/20">
        no citations
      </span>
    );
  }

  return (
    <span className="relative inline-flex flex-wrap gap-1">
      {finding.citations.map((c, i) => {
        const label = c.clause_ref ?? (c.page_number != null ? `p.${c.page_number}` : c.section_id ?? 'span');
        return (
          <span key={i} className="relative inline-flex flex-col">
            <button
              onClick={() => setOpenIdx(openIdx === i ? null : i)}
              className="inline-flex items-center gap-0.5 rounded px-1 py-px text-[9px] font-mono text-emerald-300/90 bg-emerald-500/10 border border-emerald-500/25 hover:bg-emerald-500/20 transition-colors"
            >
              {label}
            </button>
            {openIdx === i && (
              <span className="absolute left-0 top-full mt-1 z-30 w-60 rounded-md border border-emerald-500/25 bg-[#0a0d16] shadow-xl p-2 text-[9px] font-mono text-white/50 leading-relaxed text-left">
                {[c.section_id && `§${c.section_id}`, c.start_offset != null && `${c.start_offset}–${c.end_offset}`, c.source_document_id && `doc ${c.source_document_id.slice(0, 8)}`]
                  .filter(Boolean)
                  .join(' · ') || 'no span details'}
                {c.snippet && <span className="block mt-1 not-italic">"{c.snippet}"</span>}
              </span>
            )}
          </span>
        );
      })}
    </span>
  );
}

function FindingCard({ finding }: { finding: FindingRecord }) {
  const [showTrail, setShowTrail] = useState(false);
  const status = STATUS_CONFIG[finding.status] ?? STATUS_CONFIG.unqueued;

  return (
    <div className="rounded-lg border border-white/[0.06] bg-[#141927]/80 overflow-hidden">
      {/* Header */}
      <div className="px-3 pt-3 pb-2 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider border ${status.badge}`}>
            {status.label}
          </span>
          {finding.rule_id && (
            <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-mono font-medium text-indigo-300 bg-indigo-500/10 border border-indigo-500/25">
              {finding.rule_id}
            </span>
          )}
          {finding.evaluation_method && (
            <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-mono uppercase text-white/40 bg-white/[0.04] border border-white/[0.08]">
              {finding.evaluation_method}
            </span>
          )}
          {finding.severity && (
            <span className={`text-[9px] px-1 rounded font-bold uppercase ${SEV_COLORS[finding.severity] ?? SEV_COLORS.low}`}>
              {finding.severity}
            </span>
          )}
        </div>

        {/* Full description */}
        <p className="text-[12px] text-white/80 leading-relaxed break-words">{finding.description || '—'}</p>

        {/* Provenance line */}
        <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-[9px] font-mono text-white/25">
          {finding.playbook_id && <span>playbook: {finding.playbook_id}</span>}
          {finding.claim_id && <span>{finding.claim_id}</span>}
          {finding.source_node && <span>via {finding.source_node.replace(/_/g, ' ')}</span>}
          {finding.first_generated_at && (
            <span>generated {new Date(finding.first_generated_at).toLocaleString()}</span>
          )}
          <CitationChips finding={finding} />
        </div>

        {/* Decision record */}
        {finding.decided_by && (
          <div className={`rounded-md px-2.5 py-1.5 text-[10px] leading-relaxed ${
            finding.status === 'approved_needs_recheck'
              ? 'bg-amber-950/30 border border-amber-500/20 text-amber-200/70'
              : finding.status === 'approved'
                ? 'bg-emerald-950/30 border border-emerald-500/15 text-emerald-200/70'
                : 'bg-rose-950/30 border border-rose-500/15 text-rose-200/70'
          }`}>
            Decided by <span className="font-medium">{finding.decided_by}</span>
            {finding.decided_at && <> · {new Date(finding.decided_at).toLocaleString()}</>}
            {finding.justification && <div className="mt-0.5 italic">"{finding.justification}"</div>}
          </div>
        )}

        {/* Audit trail toggle */}
        {finding.events.length > 0 && (
          <button
            onClick={() => setShowTrail(!showTrail)}
            className="flex items-center gap-1.5 text-[9px] uppercase tracking-wider text-white/35 hover:text-indigo-300 transition-colors"
          >
            <svg className={`w-2.5 h-2.5 transition-transform ${showTrail ? 'rotate-90' : ''}`} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M4.5 3l3 3-3 3" />
            </svg>
            Audit trail ({finding.events.length})
          </button>
        )}

        {showTrail && (
          <div className="rounded-md border border-white/[0.06] bg-[#0a0d16] divide-y divide-white/[0.03]">
            {finding.events.map((ev) => (
              <div key={ev.event_id} className="px-2.5 py-1.5 flex items-start gap-2">
                <span className="mt-1 w-1 h-1 rounded-full bg-indigo-400/60 flex-shrink-0" />
                <div className="min-w-0 text-[9px]">
                  <span className="font-mono text-white/45">{new Date(ev.timestamp).toLocaleTimeString()}</span>
                  {' '}
                  <span className="font-semibold text-indigo-300/80">{ev.action}</span>
                  {' '}
                  <span className="text-white/35">by {ev.actor_id}</span>
                  {Object.keys(ev.details).length > 0 && (
                    <div className="font-mono text-white/25 truncate" title={JSON.stringify(ev.details)}>
                      {JSON.stringify(ev.details)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function FindingsPanel({ runId, open, onClose }: FindingsPanelProps) {
  const [data, setData] = useState<RunFindings | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'pending' | 'resolved'>('all');

  useEffect(() => {
    if (!open || !runId) {
      setData(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    fetchRunFindings(runId)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, [open, runId]);

  const visible = data
    ? data.items.filter((f) =>
        filter === 'all' ? true : filter === 'pending' ? f.status === 'pending' : ['approved', 'rejected', 'approved_needs_recheck'].includes(f.status)
      )
    : [];

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/20 z-10" onClick={onClose} />

      {/* Panel */}
      <div className="absolute top-0 right-0 h-full w-[480px] max-w-[90vw] z-20 bg-[#0c0f1a] border-l border-white/[0.06] shadow-2xl shadow-black/50 transform transition-transform duration-250 ease-out translate-x-0 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
          <div>
            <h2 className="text-sm font-semibold text-white/90">Findings — Audit Trail</h2>
            {data && (
              <p className="text-[11px] text-white/40 mt-0.5">
                {data.total} total · {data.pending} pending · {data.resolved} resolved
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border border-white/[0.08] overflow-hidden">
              {(['all', 'pending', 'resolved'] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-2 py-1 text-[10px] font-medium uppercase tracking-wider transition-colors ${
                    filter === f ? 'bg-indigo-500/20 text-indigo-300' : 'text-white/40 hover:text-white/60'
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-white/40 hover:text-white/70 hover:bg-white/[0.05] transition-colors"
              aria-label="Close panel"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {loading && (
            <div className="rounded-lg border border-white/[0.06] bg-[#141927]/60 p-3">
              <div className="flex items-center gap-2 text-xs text-white/40">
                <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <circle cx="12" cy="12" r="10" opacity={0.25} />
                  <path d="M4 12a8 8 0 018-8" opacity={0.75} />
                </svg>
                Loading findings...
              </div>
            </div>
          )}

          {!loading && error && (
            <p className="text-sm text-rose-300/70 text-center py-10">{error}</p>
          )}

          {!loading && !error && visible.length === 0 && (
            <div className="flex flex-col items-center justify-center py-14 text-center">
              <svg className="w-8 h-8 text-white/20 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1}>
                <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p className="text-xs text-white/30">
                {filter === 'all' ? 'No findings generated for this run.' : `No ${filter} findings.`}
              </p>
            </div>
          )}

          {!loading && visible.map((finding) => (
            <FindingCard key={finding.finding_key} finding={finding} />
          ))}

          {!loading && !error && data && data.items.length > 0 && (
            <p className="text-[9px] text-white/20 text-center pt-1">
              Sourced from the audit trail (audit_events) + approval queue — complete history, resolved or not.
            </p>
          )}
        </div>
      </div>
    </>
  );
}

export default FindingsPanel;
