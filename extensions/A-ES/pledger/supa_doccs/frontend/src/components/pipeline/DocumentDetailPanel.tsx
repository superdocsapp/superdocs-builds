import { useEffect, useMemo, useState } from 'react';
import {
  fetchDocumentFacts,
  type DocumentFact,
  type DocumentFactsResponse,
} from '@/services/pipelineApi';

interface DocumentDetailPanelProps {
  documentId: string;
  filename: string;
  runId?: string;
  onClose: () => void;
}

/**
 * Document detail view — every fact extracted from a document, plus a
 * raw-text tab with all cited spans highlighted inline. All values come
 * from GET /documents/{id}/facts; nothing is reconstructed client-side.
 */
export function DocumentDetailPanel({ documentId, filename, runId, onClose }: DocumentDetailPanelProps) {
  const [data, setData] = useState<DocumentFactsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'facts' | 'raw'>('facts');

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchDocumentFacts(documentId, runId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, runId]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
      onClick={onClose}
      data-testid="document-detail-overlay"
    >
      <div
        className="w-full max-w-3xl max-h-[85vh] flex flex-col rounded-xl bg-[#141420] border border-white/10 shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        data-testid="document-detail-panel"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/[0.08]">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-white/90 truncate">{filename}</h2>
            {data?.classification && (
              <p className="text-[11px] text-white/40 mt-0.5">
                classified as <span className="text-indigo-300/80">{data.classification}</span>
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-white/40 hover:text-white/80 hover:bg-white/[0.06]"
            aria-label="Close document detail"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-5 pt-2 border-b border-white/[0.08]">
          {(['facts', 'raw'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`
                px-3 py-1.5 text-[12px] font-medium rounded-t-md transition-colors
                ${tab === t
                  ? 'text-white bg-white/[0.07] border-b-2 border-indigo-400'
                  : 'text-white/45 hover:text-white/70'}
              `}
              data-testid={`tab-${t}`}
            >
              {t === 'facts' ? 'Extracted facts' : 'Raw text'}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {error && (
            <p className="text-[13px] text-rose-400" data-testid="facts-error">
              Failed to load document facts: {error}
            </p>
          )}
          {!error && !data && (
            <p className="text-[13px] text-white/40 animate-pulse" data-testid="facts-loading">
              Loading extracted facts…
            </p>
          )}
          {data && tab === 'facts' && <FactsTable facts={data.facts} />}
          {data && tab === 'raw' && <RawTextView text={data.source_text} facts={data.facts} />}
        </div>
      </div>
    </div>
  );
}

// ─── Facts tab ───────────────────────────────────────────────────────────────

function methodLabel(method: string | null): string {
  if (method === null) return 'not found';
  switch (method) {
    case 'structured':
      return 'structured';
    case 'llm':
      return 'llm';
    case 'llm_fallback':
      return 'llm (fallback)';
    case 'regex_fallback':
      return 'regex (fallback)';
    default:
      return method;
  }
}

function FactsTable({ facts }: { facts: DocumentFact[] }) {
  if (facts.length === 0) {
    return <p className="text-[13px] text-white/40 italic">No facts extracted from this document.</p>;
  }

  return (
    <table className="w-full text-left" data-testid="facts-table">
      <thead>
        <tr className="text-[10px] uppercase tracking-[0.08em] text-white/35 border-b border-white/[0.08]">
          <th className="py-2 pr-3 font-semibold">Field</th>
          <th className="py-2 pr-3 font-semibold">Value</th>
          <th className="py-2 pr-3 font-semibold">Method</th>
          <th className="py-2 font-semibold">Citation</th>
        </tr>
      </thead>
      <tbody>
        {facts.map((fact, i) => (
          <tr key={`${fact.field_name}-${i}`} className="border-b border-white/[0.04] align-top" data-testid={`fact-row-${fact.field_name}`}>
            <td className="py-2.5 pr-3 text-[12px] font-medium text-white/75 whitespace-nowrap">
              {fact.field_name}
            </td>
            <td className="py-2.5 pr-3 text-[12px] max-w-[220px]">
              {fact.extracted_value === null ? (
                <span className="italic text-white/30">not found</span>
              ) : (
                <span className="text-white/85 break-words">{fact.extracted_value}</span>
              )}
              {fact.confidence !== null && fact.extracted_value !== null && (
                <span className="block text-[10px] text-white/30 mt-0.5">
                  confidence {(fact.confidence * 100).toFixed(0)}%
                </span>
              )}
            </td>
            <td className="py-2.5 pr-3 text-[11px] text-sky-300/70 whitespace-nowrap">
              {methodLabel(fact.extraction_method)}
            </td>
            <td className="py-2.5">
              <CitationCell fact={fact} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CitationCell({ fact }: { fact: DocumentFact }) {
  if (fact.cited_span) {
    return (
      <div
        className="rounded-md bg-emerald-500/[0.08] border border-emerald-500/20 px-2.5 py-1.5 max-w-[280px]"
        data-testid="citation-grounded"
        title={`chars ${fact.cited_span.start_offset}–${fact.cited_span.end_offset}`}
      >
        <blockquote className="text-[11px] leading-snug text-emerald-200/90 line-clamp-3">
          &ldquo;{fact.cited_span.snippet}&rdquo;
        </blockquote>
        <p className="text-[9px] text-emerald-500/60 mt-1 tabular-nums">
          chars {fact.cited_span.start_offset}–{fact.cited_span.end_offset}
          {fact.cited_span.page_number !== null && ` · p.${fact.cited_span.page_number}`}
        </p>
      </div>
    );
  }

  if (fact.citation_status === 'not_found') {
    return null; // the Value column already says "not found"
  }

  // Unverifiable citation — visually distinct marker (icon + color)
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/[0.12] border border-amber-500/40 px-2.5 py-1"
      data-testid="citation-unverifiable"
    >
      <svg className="w-3 h-3 text-amber-400 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      </svg>
      <span className="text-[10px] font-medium text-amber-300 tracking-wide">
        [citation unverifiable]
      </span>
    </span>
  );
}

// ─── Raw text tab ────────────────────────────────────────────────────────────

interface Segment {
  text: string;
  highlight: boolean;
  value: string | null;
}

/**
 * Split the source text into plain/highlighted segments using the
 * server-provided span offsets — no client-side matching or guessing.
 */
function buildSegments(text: string, facts: DocumentFact[]): Segment[] {
  const spans = facts
    .filter((f) => f.cited_span !== null)
    .map((f) => ({
      start: f.cited_span!.start_offset,
      end: f.cited_span!.end_offset,
      value: f.extracted_value,
    }))
    .filter((s) => s.start >= 0 && s.end <= text.length && s.start < s.end)
    .sort((a, b) => a.start - b.start);

  const segments: Segment[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) continue; // overlapping — keep first
    if (span.start > cursor) {
      segments.push({ text: text.slice(cursor, span.start), highlight: false, value: null });
    }
    segments.push({
      text: text.slice(span.start, span.end),
      highlight: true,
      value: span.value,
    });
    cursor = span.end;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), highlight: false, value: null });
  }
  return segments;
}

function RawTextView({ text, facts }: { text: string; facts: DocumentFact[] }) {
  const segments = useMemo(() => buildSegments(text, facts), [text, facts]);
  const groundedCount = segments.filter((s) => s.highlight).length;

  return (
    <div data-testid="raw-text-view">
      <p className="text-[11px] text-white/35 mb-3">
        {groundedCount} cited span{groundedCount !== 1 ? 's' : ''} highlighted inline.
        Hover a highlight to see the extracted value.
      </p>
      <pre className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-white/70 font-mono bg-black/25 rounded-lg p-4 border border-white/[0.06]">
        {segments.map((seg, i) =>
          seg.highlight ? (
            <mark
              key={i}
              className="bg-indigo-500/30 text-indigo-100 rounded px-0.5 -mx-0.5 ring-1 ring-indigo-400/40 cursor-help"
              title={seg.value ?? undefined}
              data-testid={`highlight-${i}`}
            >
              {seg.text}
            </mark>
          ) : (
            <span key={i}>{seg.text}</span>
          ),
        )}
      </pre>
    </div>
  );
}
