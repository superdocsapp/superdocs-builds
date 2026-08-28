/**
 * Pending Review Panel — every approval-queue item for this run
 * (findings, conflicts, proposed updates) in one place.
 *
 * Fetches GET /approval/runs/{runId}/queue and wires Approve/Reject
 * to POST /approval/items/{itemId}/decide (Phase 2.3 endpoint).
 * After a decision only the decided item's local state changes —
 * the rest of the list is untouched (guaranteed by backend tests).
 */
import { useState, useEffect, useCallback } from 'react';
import type { QueueItem, ItemType } from '@/types/review';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

interface PendingReviewPanelProps {
  runId: string | null;
  open: boolean;
  onClose: () => void;
  /** Notifies parent with the updated pending count after any decision */
  onPendingCountChange?: (count: number) => void;
}

const TYPE_CONFIG: Record<ItemType | string, { label: string; border: string; badge: string; icon: React.ReactNode }> = {
  finding: {
    label: 'Finding',
    border: 'border-l-rose-500',
    badge: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path d="M12 9v4m0 3h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      </svg>
    ),
  },
  conflict: {
    label: 'Conflict',
    border: 'border-l-amber-500',
    badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path d="M8 3H5a2 2 0 00-2 2v14a2 2 0 002 2h3m8-18h3a2 2 0 012 2v14a2 2 0 01-2 2h-3M12 8v8" />
      </svg>
    ),
  },
  proposed_update: {
    label: 'Proposed Change',
    border: 'border-l-violet-500',
    badge: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
      </svg>
    ),
  },
};

function CitationCard({ citation, sideLabel }: { citation: QueueItem['payload']['source_citations'][number]; sideLabel?: string }) {
  const isUnverifiable = citation.citation_status === 'unverifiable' || !citation.source_location;

  return (
    <div className={`rounded-md border overflow-hidden ${isUnverifiable ? 'border-rose-500/20 bg-rose-950/20' : 'border-white/[0.06] bg-[#0a0d16]'}`}>
      {sideLabel && (
        <div className="px-3 pt-2 flex items-center gap-1.5">
          <span className="text-[9px] font-bold uppercase tracking-wider text-white/35">{sideLabel}</span>
          {isUnverifiable && (
            <span className="text-[9px] font-bold uppercase tracking-wider text-rose-300/80 animate-pulse">unverifiable</span>
          )}
        </div>
      )}
      <p className="text-[11px] text-white/60 leading-relaxed px-3 py-2">{citation.claim_text}</p>
      {citation.source_location && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pb-2 text-[9px] font-mono text-white/30">
          <span className="inline-flex items-center rounded px-1 py-0.5 text-emerald-300/70 bg-emerald-500/10 border border-emerald-500/20">
            {citation.source_location.clause_ref ?? `p.${citation.source_location.page_number}`}
          </span>
          {citation.source_location.section_id && <span>§{citation.source_location.section_id}</span>}
          <span>offsets {citation.source_location.start_offset}–{citation.source_location.end_offset}</span>
          {citation.snippet && (
            <span className="text-indigo-300/50 italic">"{citation.snippet.slice(0, 120)}{citation.snippet.length > 120 ? '…' : ''}"</span>
          )}
        </div>
      )}
      {!citation.source_location && (
        <div className="px-3 pb-2 text-[9px] text-rose-300/60">
          No traceable source span — manual verification required.
        </div>
      )}
    </div>
  );
}

function ReviewItemCard({ item, onDecision }: {
  item: QueueItem;
  onDecision: (id: string, decision: 'approved' | 'rejected') => Promise<void>;
}) {
  const [submitting, setSubmitting] = useState<'approved' | 'rejected' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cfg = TYPE_CONFIG[item.item_type] ?? TYPE_CONFIG.finding;
  const details = (item.payload.details ?? {}) as Record<string, unknown>;
  const evalMethod = details.evaluation_method as string | undefined;
  const confidence = typeof details.confidence === 'number' ? details.confidence : undefined;
  const severity = details.severity as string | undefined;
  const ruleId = details.rule_id as string | undefined;
  const claimId = details.claim_id as string | undefined;
  const targetSection = details.target_section as string | undefined;
  const updateType = details.update_type as string | undefined;
  const sections = details.sections as string[] | undefined;

  // Full description — never truncated
  const summary = item.payload.summary ?? '';
  const reasonText =
    (details.reason as string) ??
    (details.description as string) ??
    (details.rationale as string) ??
    null;

  const isConflict = item.item_type === 'conflict';
  const isPending = item.status === 'pending';

  const handleDecision = async (decision: 'approved' | 'rejected') => {
    setSubmitting(decision);
    setError(null);
    try {
      await onDecision(item.id, decision);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Decision failed');
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <div className={`rounded-lg border border-white/[0.06] bg-[#141927]/80 border-l-[3px] ${cfg.border} overflow-hidden`}>
      {/* Header row */}
      <div className="px-3 pt-3 pb-2">
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider border ${cfg.badge}`}>
            {cfg.icon}
            {cfg.label}
          </span>
          {evalMethod && (
            <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-mono uppercase text-white/40 bg-white/[0.04] border border-white/[0.08]" title="Evaluation method">
              {evalMethod}
            </span>
          )}
          {severity && (
            <span className={`text-[9px] px-1 rounded font-bold uppercase ${
              severity === 'high' ? 'bg-rose-500/20 text-rose-300' :
              severity === 'medium' ? 'bg-amber-500/20 text-amber-300' :
              'bg-white/10 text-white/50'
            }`}>{severity} severity</span>
          )}
          {!isPending && (
            <span className={`ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
              item.status === 'approved' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'
            }`}>
              {item.status === 'approved' ? '✓' : '✗'} {item.status}
              {item.reviewer_id && <span className="opacity-60">· {item.reviewer_id}</span>}
            </span>
          )}
        </div>

        {/* Full description */}
        <p className="text-sm text-white/85 leading-relaxed whitespace-pre-wrap break-words">{summary || '—'}</p>
        {reasonText && (
          <p className="mt-1.5 text-[11px] text-white/50 leading-relaxed">{reasonText}</p>
        )}

        {/* Metadata chips */}
        {(ruleId || claimId || targetSection || updateType || (sections && sections.length > 0)) && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-[9px] font-mono text-white/30">
            {ruleId && <span className="text-indigo-300/60">{ruleId}</span>}
            {claimId && <span>{claimId}</span>}
            {targetSection && <span>target §{targetSection}</span>}
            {updateType && <span>update: {updateType}</span>}
            {sections?.map((s) => <span key={s}>§{s}</span>)}
            <span>queued {new Date(item.queued_at).toLocaleString()}</span>
          </div>
        )}

        {/* Confidence signal */}
        {confidence != null && (
          <div className="flex items-center gap-2 mt-2">
            <span className="text-[9px] uppercase tracking-wider text-white/30 w-16">Confidence</span>
            <div className="flex-1 h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
              <div
                className={`h-full rounded-full ${confidence >= 0.8 ? 'bg-emerald-500/60' : confidence >= 0.5 ? 'bg-amber-500/60' : 'bg-rose-500/60'}`}
                style={{ width: `${Math.round(confidence * 100)}%` }}
              />
            </div>
            <span className={`text-[10px] font-mono ${confidence >= 0.8 ? 'text-emerald-300/70' : confidence >= 0.5 ? 'text-amber-300/70' : 'text-rose-300/70'}`}>
              {(confidence * 100).toFixed(0)}%
            </span>
          </div>
        )}
      </div>

      {/* Citations — both sides shown for conflicts */}
      {item.payload.source_citations?.length > 0 && (
        <div className="px-3 pb-2 space-y-1.5">
          <span className="text-[9px] font-semibold uppercase tracking-wider text-white/30 block">
            {isConflict ? 'Conflicting Sources' : 'Source Citations'}
          </span>
          {item.payload.source_citations.map((cit, idx) => (
            <CitationCard
              key={cit.claim_id}
              citation={cit}
              sideLabel={isConflict ? `Side ${String.fromCharCode(65 + idx)}` : undefined}
            />
          ))}
        </div>
      )}

      {/* Decision actions */}
      {isPending && (
        <div className="flex border-t border-white/[0.04]">
          <button
            onClick={() => handleDecision('approved')}
            disabled={submitting !== null}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/10 transition-colors disabled:opacity-40 border-r border-white/[0.04]"
          >
            {submitting === 'approved' ? (
              <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><circle cx="12" cy="12" r="10" opacity={0.25} /><path d="M4 12a8 8 0 018-8" opacity={0.75} /></svg>
            ) : (
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M5 12l5 5L20 7" /></svg>
            )}
            Approve
          </button>
          <button
            onClick={() => handleDecision('rejected')}
            disabled={submitting !== null}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium text-rose-300 hover:bg-rose-500/10 transition-colors disabled:opacity-40"
          >
            {submitting === 'rejected' ? (
              <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><circle cx="12" cy="12" r="10" opacity={0.25} /><path d="M4 12a8 8 0 018-8" opacity={0.75} /></svg>
            ) : (
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M18 6L6 18M6 6l12 12" /></svg>
            )}
            Reject
          </button>
        </div>
      )}

      {error && (
        <div className="px-3 py-1.5 bg-rose-950/30 border-t border-rose-500/20 text-[10px] text-rose-300">{error}</div>
      )}
    </div>
  );
}

export function PendingReviewPanel({ runId, open, onClose, onPendingCountChange }: PendingReviewPanelProps) {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'pending' | 'all'>('pending');

  // Fetch queue for this run
  const fetchQueue = useCallback(async (): Promise<QueueItem[]> => {
    if (!runId) return [];
    const res = await fetch(`${BASE_URL}/approval/runs/${runId}/queue`);
    if (!res.ok) throw new Error(`Failed to load queue (${res.status})`);
    let data = await res.json();

    // Best-effort backfill if the queue was never populated for this run
    if (data.total === 0) {
      try {
        const backfillRes = await fetch(`${BASE_URL}/runs/${runId}/populate-queue`, { method: 'POST' });
        if (backfillRes.ok) {
          const backfill = await backfillRes.json();
          if (backfill.created > 0) {
            const refetch = await fetch(`${BASE_URL}/approval/runs/${runId}/queue`);
            if (refetch.ok) data = await refetch.json();
          }
        }
      } catch { /* best-effort */ }
    }

    const fetchedItems: QueueItem[] = data.items ?? [];
    setItems(fetchedItems);
    onPendingCountChange?.(fetchedItems.filter((i) => i.status === 'pending').length);
    return fetchedItems;
  }, [runId, onPendingCountChange]);

  useEffect(() => {
    if (!open || !runId) {
      setItems([]);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    fetchQueue()
      .catch((err) => setError(err instanceof Error ? err.message : 'Network error'))
      .finally(() => setLoading(false));
  }, [open, runId, fetchQueue]);

  // Decision handler — POST to real endpoint, then update ONLY this item locally
  const handleDecision = useCallback(async (itemId: string, decision: 'approved' | 'rejected') => {
    const res = await fetch(`${BASE_URL}/approval/items/${itemId}/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        decision,
        reviewer_id: 'current-user',
        justification: `${decision} via Pending Review tab`,
      }),
    });
    if (!res.ok) {
      throw new Error(`Decision failed (${res.status})`);
    }
    // Surgical local update — other items are untouched
    setItems((prev) => {
      const next = prev.map((item) =>
        item.id === itemId
          ? { ...item, status: decision, decision, decided_at: new Date().toISOString(), reviewer_id: 'current-user' }
          : item
      );
      onPendingCountChange?.(next.filter((i) => i.status === 'pending').length);
      return next;
    });
  }, [onPendingCountChange]);

  if (!open) return null;

  const pendingItems = items.filter((i) => i.status === 'pending');
  const visibleItems = filter === 'pending' ? pendingItems : items;
  const counts = {
    finding: items.filter((i) => i.item_type === 'finding' && i.status === 'pending').length,
    conflict: items.filter((i) => i.item_type === 'conflict' && i.status === 'pending').length,
    proposed_update: items.filter((i) => i.item_type === 'proposed_update' && i.status === 'pending').length,
  };

  return (
    <>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/20 z-10" onClick={onClose} />

      {/* Panel */}
      <div className="absolute top-0 right-0 h-full w-[480px] max-w-[90vw] z-20 bg-[#0c0f1a] border-l border-white/[0.06] shadow-2xl shadow-black/50 transform transition-transform duration-250 ease-out translate-x-0 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
          <div>
            <h2 className="text-sm font-semibold text-white/90 flex items-center gap-2">
              Pending Review
              {pendingItems.length > 0 && (
                <span className="inline-flex items-center rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300 border border-amber-500/30">
                  {pendingItems.length} awaiting decision
                </span>
              )}
            </h2>
            <div className="flex items-center gap-2 mt-1 text-[10px] text-white/35">
              <span>{counts.finding} findings</span>
              <span>·</span>
              <span>{counts.conflict} conflicts</span>
              <span>·</span>
              <span>{counts.proposed_update} proposed changes</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Filter toggle */}
            <div className="flex rounded-md border border-white/[0.08] overflow-hidden">
              {(['pending', 'all'] as const).map((f) => (
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
                Loading approval queue...
              </div>
            </div>
          )}

          {!loading && error && (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <p className="text-sm text-rose-300/70">{error}</p>
              <button
                onClick={() => { setLoading(true); fetchQueue().catch(() => {}).finally(() => setLoading(false)); }}
                className="mt-3 rounded-md px-3 py-1.5 text-xs text-white/70 border border-white/[0.1] hover:bg-white/[0.05] transition-colors"
              >
                Retry
              </button>
            </div>
          )}

          {!loading && !error && visibleItems.length === 0 && (
            <div className="flex flex-col items-center justify-center py-14 text-center">
              <svg className="w-8 h-8 text-emerald-400/40 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-xs text-white/40">
                {filter === 'pending' ? 'Nothing waiting on a human.' : 'No items in the queue.'}
              </p>
              {filter === 'pending' && items.length > 0 && (
                <button
                  onClick={() => setFilter('all')}
                  className="mt-2 text-[11px] text-indigo-300 hover:text-indigo-200 underline underline-offset-2"
                >
                  Show decided items ({items.length})
                </button>
              )}
            </div>
          )}

          {!loading && visibleItems.map((item) => (
            <ReviewItemCard key={item.id} item={item} onDecision={handleDecision} />
          ))}
        </div>
      </div>
    </>
  );
}

export default PendingReviewPanel;
