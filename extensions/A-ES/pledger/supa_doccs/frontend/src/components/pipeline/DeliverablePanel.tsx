/**
 * Deliverable Panel — the assembled register produced by Movement 1
 * (finalize) and mutated by Movement 3 incremental updates.
 *
 * Data sources (no client-side recomputation):
 *   GET /runs/{id}/deliverable — sections + claims with inline citations
 *   GET /runs/{id}/history     — incremental_update audit events for the diff
 *
 * Every claim line shows its source citation inline. A line whose claim
 * has no source span (citation_status='unverifiable' or missing citation)
 * carries a visually loud UNVERIFIABLE marker per Prompt 3.6.
 */
import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  fetchRunDeliverable,
  fetchRunHistory,
  type RunDeliverable,
  type DeliverableSection,
  type DeliverableClaim,
  type HistoryEntry,
} from '@/services/pipelineApi';

interface DeliverablePanelProps {
  runId: string | null;
  open: boolean;
  onClose: () => void;
}

/** An incremental update event pulled from /history */
interface IncrementalEvent {
  eventId: string;
  timestamp: string;
  newDocumentId: string | null;
  affectedSections: string[];
  conflictsDetected: number;
  approvalItemsCreated: number;
  sectionHashesBefore: Record<string, string>;
}

function parseIncrementalEvents(entries: HistoryEntry[]): IncrementalEvent[] {
  return entries
    .filter((e) => (e.new_state as Record<string, unknown> | null)?.type === 'incremental_update')
    .map((e) => {
      const ns = (e.new_state ?? {}) as Record<string, any>;
      const ps = (e.previous_state ?? {}) as Record<string, any>;
      return {
        eventId: e.event_id,
        timestamp: e.timestamp,
        newDocumentId: e.source_document_id ?? ns.document_id ?? null,
        affectedSections: Array.isArray(ns.affected_sections) ? ns.affected_sections : [],
        conflictsDetected: ns.conflicts_detected ?? 0,
        approvalItemsCreated: ns.approval_items_created ?? 0,
        sectionHashesBefore: ps.section_hashes ?? {},
      };
    });
}

// ─── Citation chip ───────────────────────────────────────────────────────────

function InlineCitation({ claim }: { claim: DeliverableClaim }) {
  const [showSnippet, setShowSnippet] = useState(false);
  const citation = claim.citation;

  if (!citation || (!citation.clause_ref && citation.page_number == null && !citation.section_id)) {
    return null; // unverifiable rendering handled by the line itself
  }

  const label =
    citation.clause_ref ??
    (citation.page_number != null ? `p.${citation.page_number}` : citation.section_id!);
  const meta = [
    citation.section_id ? `§${citation.section_id}` : null,
    citation.start_offset != null && citation.end_offset != null
      ? `${citation.start_offset}–${citation.end_offset}`
      : null,
  ].filter(Boolean).join(' · ');

  return (
    <span className="relative inline-flex flex-col align-baseline">
      <button
        onClick={() => citation.snippet && setShowSnippet(!showSnippet)}
        className="inline-flex items-center gap-0.5 mx-1 rounded px-1 py-px align-middle text-[9px] font-mono text-emerald-300/90 bg-emerald-500/10 border border-emerald-500/25 hover:bg-emerald-500/20 transition-colors"
        title={meta || 'Source location'}
      >
        <svg className="w-2.5 h-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
        </svg>
        {label}
      </button>
      {showSnippet && citation.snippet && (
        <span className="absolute left-0 top-full mt-1 z-30 w-64 rounded-md border border-emerald-500/25 bg-[#0a0d16] shadow-xl p-2 text-[10px] text-white/60 leading-relaxed">
          <span className="block text-[8px] uppercase tracking-wider text-white/30 mb-1">
            Source excerpt {meta ? `· ${meta}` : ''}
          </span>
          "{citation.snippet}"
        </span>
      )}
    </span>
  );
}

// ─── Claim line ──────────────────────────────────────────────────────────────

function ClaimLine({ claim, changed }: { claim: DeliverableClaim; changed: boolean }) {
  const isUnverifiable =
    claim.citation_status === 'unverifiable' ||
    claim.citation_status === 'not_found' ||
    !claim.citation;

  return (
    <div
      className={`flex items-start gap-2 px-2.5 py-2 border-l-[3px] transition-colors ${
        isUnverifiable
          ? 'border-l-rose-500 bg-rose-950/25 hover:bg-rose-950/35'
          : changed
            ? 'border-l-indigo-400 bg-indigo-500/[0.06] hover:bg-indigo-500/[0.1]'
            : 'border-l-transparent hover:bg-white/[0.02]'
      }`}
    >
      {/* Unverifiable marker — must be impossible to miss */}
      {isUnverifiable && (
        <span className="flex-shrink-0 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider bg-rose-500/25 text-rose-200 border border-rose-400/40 animate-pulse">
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M12 9v4m0 3h.01M12 3l9.5 16.5H2.5L12 3z" />
          </svg>
          Unverifiable
        </span>
      )}
      {changed && !isUnverifiable && (
        <span className="flex-shrink-0 inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider bg-indigo-500/20 text-indigo-300 border border-indigo-400/30">
          Updated
        </span>
      )}

      <div className="flex-1 min-w-0">
        <p className="text-[12px] leading-relaxed text-white/75">
          {claim.extracted_text}
          <InlineCitation claim={claim} />
        </p>
        <div className="flex items-center gap-2 mt-0.5 flex-wrap text-[9px] font-mono text-white/25">
          <span>{claim.claim_id}</span>
          <span>conf {(claim.confidence * 100).toFixed(0)}%</span>
          <span className="truncate max-w-[140px]" title={claim.source_document_id}>
            doc {claim.source_document_id.slice(0, 8)}
          </span>
          {isUnverifiable && (
            <span className="text-rose-300/60">no source span recorded at extraction</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Section card ────────────────────────────────────────────────────────────

function SectionCard({
  section,
  changedSectionKeys,
  hashBefore,
}: {
  section: DeliverableSection;
  changedSectionKeys: Set<string>;
  hashBefore?: string | null;
}) {
  const [open, setOpen] = useState(true);
  const changed = changedSectionKeys.has(section.key);
  const unverifiableCount = section.claims.filter(
    (c) => c.citation_status === 'unverifiable' || c.citation_status === 'not_found' || !c.citation
  ).length;

  return (
    <div className={`rounded-lg border overflow-hidden ${
      changed ? 'border-indigo-400/30' : 'border-white/[0.06]'
    } bg-[#141927]/70`}>
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-2 px-3 py-2 hover:bg-white/[0.02] text-left">
        <svg className={`w-3 h-3 text-white/30 transition-transform ${open ? '' : '-rotate-90'}`} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M3 4.5l3 3 3-3" />
        </svg>
        <span className="text-[11px] font-semibold text-white/70">{section.key.replace(/[._]/g, ' ')}</span>
        <span className="text-[9px] font-mono text-white/25">{section.claims.length} claims</span>
        {changed && (
          <span className="inline-flex items-center rounded px-1.5 py-px text-[9px] font-bold uppercase bg-indigo-500/20 text-indigo-300 border border-indigo-400/30">
            Changed by update
          </span>
        )}
        {unverifiableCount > 0 && (
          <span className="inline-flex items-center gap-1 rounded px-1.5 py-px text-[9px] font-bold uppercase bg-rose-500/15 text-rose-300 border border-rose-500/30">
            {unverifiableCount} unverifiable
          </span>
        )}
        <span className="ml-auto text-[8px] font-mono text-white/20 truncate max-w-[80px]" title={`hash ${section.content_hash}`}>
          #{section.content_hash.slice(0, 8)}
        </span>
      </button>

      {open && (
        <div className="divide-y divide-white/[0.03] border-t border-white/[0.04]">
          {section.claims.map((claim) => (
            <ClaimLine key={claim.claim_id} claim={claim} changed={changed} />
          ))}
        </div>
      )}

      {/* Hash provenance for sections touched by an incremental update */}
      {changed && hashBefore && (
        <div className="px-3 py-1.5 bg-indigo-950/20 border-t border-indigo-500/10 text-[9px] font-mono text-indigo-300/60">
          hash before update: {hashBefore.slice(0, 16)}… → now {section.content_hash.slice(0, 16)}…
        </div>
      )}
    </div>
  );
}

// ─── Main panel ──────────────────────────────────────────────────────────────

export function DeliverablePanel({ runId, open, onClose }: DeliverablePanelProps) {
  const [deliverable, setDeliverable] = useState<RunDeliverable | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<IncrementalEvent[]>([]);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);

  const loadAll = useCallback(async (rid: string) => {
    // Deliverable and history fetched independently — history failures
    // shouldn't hide the deliverable.
    const deliverableResult = await fetchRunDeliverable(rid);
    setDeliverable(deliverableResult);

    try {
      const history = await fetchRunHistory(rid);
      setEvents(parseIncrementalEvents(history.entries));
    } catch {
      setEvents([]);
    }
  }, []);

  useEffect(() => {
    if (!open || !runId) {
      setDeliverable(null);
      setError(null);
      setEvents([]);
      setSelectedEventId(null);
      return;
    }
    setLoading(true);
    setError(null);
    setSelectedEventId(null);
    loadAll(runId)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, [open, runId, loadAll]);

  // Sections changed by the selected incremental update:
  // listed as affected AND whose current hash differs from the pre-update hash.
  const selectedEvent = useMemo(
    () => events.find((e) => e.eventId === selectedEventId) ?? null,
    [events, selectedEventId]
  );

  const changedSectionKeys = useMemo(() => {
    if (!selectedEvent || !deliverable) return new Set<string>();
    return new Set(
      selectedEvent.affectedSections.filter((key) => {
        const before = selectedEvent.sectionHashesBefore[key];
        const section = deliverable.sections[key];
        return section ? before == null || before !== section.content_hash : false;
      })
    );
  }, [selectedEvent, deliverable]);

  const totalUnverifiable = useMemo(() => {
    if (!deliverable) return 0;
    return Object.values(deliverable.sections).reduce(
      (acc, s) =>
        acc + s.claims.filter(
          (c) => c.citation_status === 'unverifiable' || c.citation_status === 'not_found' || !c.citation
        ).length,
      0
    );
  }, [deliverable]);

  if (!open) return null;

  const sortedSections = deliverable
    ? Object.values(deliverable.sections).sort((a, b) => a.key.localeCompare(b.key))
    : [];

  return (
    <>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/20 z-10" onClick={onClose} />

      {/* Panel */}
      <div className="absolute top-0 right-0 h-full w-[520px] max-w-[92vw] z-20 bg-[#0c0f1a] border-l border-white/[0.06] shadow-2xl shadow-black/50 transform transition-transform duration-250 ease-out translate-x-0 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-white/90">Deliverable Register</h2>
            {deliverable ? (
              <div className="flex items-center gap-2 mt-0.5 text-[10px] text-white/35 flex-wrap">
                <span className="font-mono">#{deliverable.deliverable_hash.slice(0, 12)}</span>
                <span>·</span>
                <span>{deliverable.section_count} sections</span>
                <span>·</span>
                <span>{deliverable.claim_count} claims</span>
                {totalUnverifiable > 0 && (
                  <>
                    <span>·</span>
                    <span className="text-rose-300/80 font-medium">{totalUnverifiable} unverifiable</span>
                  </>
                )}
              </div>
            ) : (
              <p className="text-[11px] text-white/40 mt-0.5">Assembled pipeline output</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-white/40 hover:text-white/70 hover:bg-white/[0.05] transition-colors flex-shrink-0"
            aria-label="Close panel"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
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
                Loading deliverable...
              </div>
            </div>
          )}

          {!loading && error && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <p className="text-sm text-white/40">{error.includes('404') ? 'No deliverable yet.' : error}</p>
              <p className="text-xs text-white/25 mt-1">
                The register appears after the finalize node completes.
              </p>
            </div>
          )}

          {/* Change log from Movement 3 incremental updates (/runs/{id}/history) */}
          {!loading && !error && events.length > 0 && (
            <div className="rounded-lg border border-indigo-500/20 bg-indigo-950/10 overflow-hidden">
              <button
                onClick={() => setSelectedEventId(selectedEventId ? null : events[0].eventId)}
                className="w-full flex items-center justify-between px-3 py-2 hover:bg-white/[0.02]"
              >
                <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-300/80 flex items-center gap-1.5">
                  <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                  </svg>
                  Update History ({events.length})
                </span>
                <svg className={`w-3 h-3 text-white/30 transition-transform ${selectedEventId ? 'rotate-180' : ''}`} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path d="M3 4.5l3 3 3-3" />
                </svg>
              </button>

              {(selectedEventId ? events.filter((e) => e.eventId === selectedEventId) : events).map((ev) => (
                <div key={ev.eventId} className="px-3 py-2 border-t border-indigo-500/10">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-[10px] text-white/45">
                        {new Date(ev.timestamp).toLocaleString()} — incremental update applied
                      </div>
                      <div className="text-[10px] text-white/60 mt-0.5">
                        Caused by new document{' '}
                        <button
                          onClick={() => setSelectedEventId(ev.eventId)}
                          className={`font-mono underline underline-offset-2 decoration-dotted ${
                            selectedEventId === ev.eventId ? 'text-indigo-300' : 'text-indigo-300/70 hover:text-indigo-200'
                          }`}
                        >
                          {ev.newDocumentId?.slice(0, 8) ?? 'unknown'}
                        </button>
                      </div>
                    </div>
                    <div className="flex-shrink-0 text-right space-y-0.5">
                      <div className="text-[10px] font-medium text-indigo-300">{ev.affectedSections.length} sections</div>
                      {ev.conflictsDetected > 0 && (
                        <div className="text-[9px] text-amber-300/80">{ev.conflictsDetected} conflicts</div>
                      )}
                    </div>
                  </div>
                  {ev.affectedSections.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {ev.affectedSections.map((s) => (
                        <span
                          key={s}
                          className={`rounded px-1.5 py-px text-[9px] font-mono border ${
                            changedSectionKeys.has(s)
                              ? 'bg-indigo-500/20 text-indigo-200 border-indigo-400/40'
                              : 'bg-white/[0.04] text-white/40 border-white/[0.08]'
                          }`}
                        >
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {selectedEventId && (
                <div className="px-3 py-1.5 border-t border-indigo-500/10 bg-indigo-950/20">
                  <p className="text-[9px] text-indigo-200/60">
                    Highlighted sections below changed content since this update (hash comparison from history).
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Sections */}
          {!loading && !error && sortedSections.map((section) => (
            <SectionCard
              key={section.key}
              section={section}
              changedSectionKeys={changedSectionKeys}
              hashBefore={selectedEvent?.sectionHashesBefore[section.key]}
            />
          ))}

          {!loading && !error && sortedSections.length === 0 && (
            <div className="flex flex-col items-center justify-center py-14 text-center">
              <svg className="w-8 h-8 text-white/20 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1}>
                <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p className="text-xs text-white/30">No deliverable registered for this run yet.</p>
            </div>
          )}

          {/* Unverifiable legend */}
          {!loading && !error && sortedSections.length > 0 && (
            <div className="flex items-center gap-2 px-3 py-2 text-[9px] text-white/25 border-t border-white/[0.04]">
              <span className="inline-block w-2 h-2 rounded-sm bg-rose-500/50" />
              Unverifiable lines had no traceable source span at extraction time.
              <span className="inline-block w-2 h-2 rounded-sm bg-indigo-400/60 ml-2" />
              Indigo lines were modified by an incremental update.
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export default DeliverablePanel;
