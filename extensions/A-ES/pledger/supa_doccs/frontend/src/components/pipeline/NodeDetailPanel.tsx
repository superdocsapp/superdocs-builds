/**
 * Slide-in detail panel for pipeline nodes.
 * Shows findings/conflicts/proposed-updates for Examine-stage nodes with
 * approve/reject actions. Decisions are per-item and don't affect others.
 */
import { useState, useCallback, useEffect } from 'react';
import type { QueueItem, SourceCitation } from '@/types/review';

// ─── Mock items per node (dev mode) ─────────────────────────────────────────

const MOCK_NODE_ITEMS: Record<string, QueueItem[]> = {
  extract_claims: [
    {
      id: 'item-ec-1',
      run_id: 'run-001',
      item_type: 'finding',
      payload: {
        summary: 'Capital adequacy ratio below regulatory minimum (8.5% vs 10% required)',
        details: { severity: 'high', rule_id: 'CAP-4.2', evaluation_method: 'llm' },
        source_citations: [{
          claim_id: 'c1',
          claim_text: 'The institution maintains a capital ratio of 8.5%',
          citation_status: 'grounded',
          source_location: { page_number: 12, section_id: 'sec-4.2', start_offset: 145, end_offset: 210, clause_ref: '§4.2.1' },
        }],
      },
      status: 'pending',
      queued_at: '2024-06-01T10:15:00Z',
      decided_at: null, decision: null, reviewer_id: null, justification: null,
    },
    {
      id: 'item-ec-2',
      run_id: 'run-001',
      item_type: 'conflict',
      payload: {
        summary: 'Conflicting LTV ratios stated in sections 3.1 and 5.4',
        details: { severity: 'medium', sections: ['3.1', '5.4'], evaluation_method: 'structured' },
        source_citations: [
          { claim_id: 'c2', claim_text: 'Maximum LTV ratio is 80%', citation_status: 'grounded', source_location: { page_number: 8, section_id: 'sec-3.1', start_offset: 50, end_offset: 95, clause_ref: '§3.1.3' } },
          { claim_id: 'c3', claim_text: 'LTV ratios may exceed thresholds', citation_status: 'unverifiable', source_location: null },
        ],
      },
      status: 'pending',
      queued_at: '2024-06-01T10:20:00Z',
      decided_at: null, decision: null, reviewer_id: null, justification: null,
    },
  ],
  match_rules: [
    {
      id: 'item-mr-1',
      run_id: 'run-001',
      item_type: 'proposed_update',
      payload: {
        summary: 'Update interest rate disclosure to match revised APR guidance',
        details: { target_section: '6.1', update_type: 'language', evaluation_method: 'llm' },
        source_citations: [{
          claim_id: 'c4',
          claim_text: 'Interest rates shall be disclosed in APR format',
          citation_status: 'grounded',
          source_location: { page_number: 22, section_id: 'sec-6.1', start_offset: 0, end_offset: 55, clause_ref: '§6.1.2' },
        }],
      },
      status: 'pending',
      queued_at: '2024-06-01T10:25:00Z',
      decided_at: null, decision: null, reviewer_id: null, justification: null,
    },
  ],
  score_confidence: [
    {
      id: 'item-sc-1',
      run_id: 'run-001',
      item_type: 'finding',
      payload: {
        summary: 'Missing fee schedule disclosure for Q3 2024 changes',
        details: { severity: 'low', rule_id: 'DISC-7.3', evaluation_method: 'structured' },
        source_citations: [
          { claim_id: 'c5', claim_text: 'Fee schedules updated March 2024', citation_status: 'unverifiable', source_location: null },
          { claim_id: 'c6', claim_text: 'Customers notified 30 days prior', citation_status: 'grounded', source_location: { page_number: 5, section_id: 'sec-7.3', start_offset: 200, end_offset: 270, clause_ref: null } },
        ],
      },
      status: 'pending',
      queued_at: '2024-06-01T10:30:00Z',
      decided_at: null, decision: null, reviewer_id: null, justification: null,
    },
  ],
};

const USE_MOCK = import.meta.env.VITE_MOCK_API === 'true';
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

// ─── Citation component ──────────────────────────────────────────────────────

function CitationView({ citation, expanded, onToggle }: { citation: SourceCitation; expanded: boolean; onToggle: () => void }) {
  const isUnverifiable = citation.citation_status === 'unverifiable' || !citation.source_location;

  return (
    <div className="rounded-md border border-white/[0.06] bg-[#0f1320]/60 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-start gap-2 px-3 py-2 text-left hover:bg-white/[0.02] transition-colors"
      >
        {isUnverifiable ? (
          <div className="flex items-center gap-1.5 flex-1">
            <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-rose-500/20 text-rose-300 border border-rose-500/30 animate-pulse">
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path d="M12 9v4m0 3h.01M12 3l9.5 16.5H2.5L12 3z" />
              </svg>
              UNVERIFIABLE
            </span>
            <span className="text-xs text-white/50 truncate">{citation.claim_text}</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 flex-1">
            <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-mono text-emerald-300/80 bg-emerald-500/10 border border-emerald-500/20">
              {citation.source_location!.clause_ref ?? `p.${citation.source_location!.page_number}`}
            </span>
            <span className="text-xs text-white/50 truncate">{citation.claim_text}</span>
          </div>
        )}
        <svg className={`w-3.5 h-3.5 text-white/30 transition-transform flex-shrink-0 mt-0.5 ${expanded ? 'rotate-180' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && citation.source_location && (
        <div className="px-3 py-2 border-t border-white/[0.04] bg-[#0a0d16]">
          <div className="text-[10px] uppercase tracking-wider text-white/30 mb-1">Source Document · Page {citation.source_location.page_number}</div>
          <div className="text-sm text-white/60 leading-relaxed">
            {citation.snippet ? (
              <>
                <span className="text-white/30">{citation.snippet_context_before ? `...${citation.snippet_context_before}` : '...'}</span>
                <mark className="bg-indigo-500/20 text-indigo-200 px-0.5 rounded-sm border-b border-indigo-400/50">
                  {citation.snippet}
                </mark>
                <span className="text-white/30">{citation.snippet_context_after ? `${citation.snippet_context_after}...` : '...'}</span>
              </>
            ) : (
              <>
                <span className="text-white/30">...preceding text content... </span>
                <mark className="bg-indigo-500/20 text-indigo-200 px-0.5 rounded-sm border-b border-indigo-400/50">
                  {citation.claim_text}
                </mark>
                <span className="text-white/30"> ...following text content...</span>
              </>
            )}
          </div>
          <div className="mt-1.5 flex gap-3 text-[10px] text-white/30">
            <span>Section: {citation.source_location.section_id ?? '—'}</span>
            <span>Offset: {citation.source_location.start_offset}–{citation.source_location.end_offset}</span>
          </div>
        </div>
      )}

      {expanded && !citation.source_location && (
        <div className="px-3 py-3 border-t border-rose-500/10 bg-rose-950/20">
          <div className="flex items-center gap-2 text-rose-300 text-xs">
            <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
              <path d="M12 9v4m0 3h.01M12 3l9.5 16.5H2.5L12 3z" />
            </svg>
            <span>No source span available. This citation could not be traced to a specific document location. Manual verification required.</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Single item card ────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, { border: string; badge: string }> = {
  finding: { border: 'border-l-rose-500', badge: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  conflict: { border: 'border-l-amber-500', badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  proposed_update: { border: 'border-l-violet-500', badge: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
};

function ItemCard({ item, onDecision }: { item: QueueItem; onDecision: (id: string, decision: 'approved' | 'rejected') => void }) {
  const [expandedCitation, setExpandedCitation] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<'approved' | 'rejected' | null>(null);
  const colors = TYPE_COLORS[item.item_type] ?? TYPE_COLORS.finding;
  const evalMethod = (item.payload.details as Record<string, unknown>).evaluation_method as string | undefined;

  const handleDecision = async (decision: 'approved' | 'rejected') => {
    setSubmitting(decision);
    await onDecision(item.id, decision);
    setSubmitting(null);
  };

  const isPending = item.status === 'pending';

  return (
    <div className={`rounded-lg border border-white/[0.06] bg-[#141927]/80 border-l-[3px] ${colors.border} overflow-hidden`}>
      {/* Header */}
      <div className="px-3 py-2.5">
        <div className="flex items-center gap-2 mb-1.5">
          <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider border ${colors.badge}`}>
            {item.item_type.replace('_', ' ')}
          </span>
          {evalMethod && (
            <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-mono uppercase text-white/30 bg-white/[0.03] border border-white/[0.08]">
              {evalMethod}
            </span>
          )}
          {!isPending && (
            <span className={`ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
              item.status === 'approved' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'
            }`}>
              {item.status === 'approved' ? '✓' : '✗'} {item.status}
            </span>
          )}
        </div>
        <p className="text-sm font-medium text-white/85 leading-snug">{item.payload.summary ?? (item.payload as any).claim_text ?? '—'}</p>
      </div>

      {/* Citations */}
      <div className="px-3 pb-2 space-y-1.5">
        {(item.payload.source_citations ?? []).map((cit) => (
          <CitationView
            key={cit.claim_id}
            citation={cit}
            expanded={expandedCitation === cit.claim_id}
            onToggle={() => setExpandedCitation(expandedCitation === cit.claim_id ? null : cit.claim_id)}
          />
        ))}
      </div>

      {/* Decision buttons */}
      {isPending && (
        <div className="flex border-t border-white/[0.04]">
          <button
            onClick={() => handleDecision('approved')}
            disabled={submitting !== null}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-emerald-300 hover:bg-emerald-500/10 transition-colors disabled:opacity-40 border-r border-white/[0.04]"
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
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-rose-300 hover:bg-rose-500/10 transition-colors disabled:opacity-40"
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
    </div>
  );
}

// ─── Node Details Display ────────────────────────────────────────────────────

function ErrorRetryBanner({ details }: { details: any }) {
  const hasError = details.error_detail || details.status === 'error' || details.status === 'failed';
  const hasRetries = (details.retry_count ?? 0) > 0;
  const hasSkip = !!details.skip_reason;

  if (!hasError && !hasRetries && !hasSkip) return null;

  return (
    <div className="space-y-1.5">
      {hasError && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <svg className="w-3.5 h-3.5 text-rose-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M12 9v4m0 3h.01M12 3l9.5 16.5H2.5L12 3z" />
            </svg>
            <span className="text-[10px] font-bold uppercase tracking-wider text-rose-300">
              {details.error_type === 'transient' ? 'Transient Error' : 'Permanent Error'}
            </span>
          </div>
          <p className="text-[11px] text-rose-200/80 leading-snug">{details.error_detail}</p>
        </div>
      )}
      {hasRetries && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
            <path d="M1 4v6h6M23 20v-6h-6" />
            <path d="M20.49 9A9 9 0 015.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15" />
          </svg>
          <span className="text-[11px] text-amber-200/80">Retried {details.retry_count} time{details.retry_count > 1 ? 's' : ''}</span>
        </div>
      )}
      {hasSkip && (
        <div className="rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2 flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-amber-400/70" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M13 5l7 7-7 7M5 5l7 7-7 7" />
          </svg>
          <span className="text-[11px] text-amber-200/70">Skipped: {details.skip_reason?.replace(/_/g, ' ')}</span>
        </div>
      )}
    </div>
  );
}

function MethodBadge({ method }: { method: string }) {
  const colors = method === 'llm'
    ? 'bg-violet-500/15 text-violet-300 border-violet-500/30'
    : method === 'structured' || method === 'regex_fallback'
      ? 'bg-sky-500/15 text-sky-300 border-sky-500/30'
      : 'bg-white/10 text-white/50 border-white/20';
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-mono uppercase border ${colors}`}>
      {method.replace(/_/g, ' ')}
    </span>
  );
}

function NodeDetailsSection({ details }: { details: any }) {
  if (!details || details.status === 'running') return null;

  const duration = details.duration_ms != null ? `${(details.duration_ms / 1000).toFixed(1)}s` : '—';
  const tokens = (details.input_tokens || details.output_tokens)
    ? `${details.input_tokens ?? 0} in / ${details.output_tokens ?? 0} out`
    : null;
  const cost = details.cost_usd != null ? `$${details.cost_usd.toFixed(4)}` : null;
  const nodeId = details.node_id;

  return (
    <div className="rounded-lg border border-white/[0.06] bg-[#141927]/60 overflow-hidden">
      {/* Metrics bar */}
      <div className="flex items-center gap-3 px-3 py-2 border-b border-white/[0.04] bg-[#0f1320]/40">
        <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider border ${
          details.status === 'completed' ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' :
          details.status === 'skipped' ? 'bg-amber-500/20 text-amber-300 border-amber-500/30' :
          details.status === 'error' || details.status === 'failed' ? 'bg-rose-500/20 text-rose-300 border-rose-500/30' :
          'bg-white/10 text-white/50 border-white/20'
        }`}>{details.status}</span>
        <span className="text-[10px] text-white/40 font-mono">{duration}</span>
        {tokens && <span className="text-[10px] text-white/30 font-mono">{tokens}</span>}
        {cost && <span className="text-[10px] text-violet-300/70 font-mono">{cost}</span>}
      </div>

      {/* Error / Retry / Skip banner */}
      <div className="p-3 space-y-3">
        <ErrorRetryBanner details={details} />

        {/* ── Ingest ────────────────────────────────────────────────────── */}
        {nodeId === 'ingest' && (
          <div className="space-y-1.5">
            {details.mime_type && <DetailRow label="MIME Type" value={details.mime_type} />}
            {details.file_size != null && <DetailRow label="File Size" value={`${(details.file_size / 1024).toFixed(1)} KB`} />}
            {details.pile_document_count != null && details.pile_document_count > 0 && (
              <DetailRow label="Documents in Pile" value={`${details.pile_document_count}`} />
            )}
            {details.document_id && (
              <DetailRow label="Primary Document" value={details.document_id.slice(0, 8) + '...'} />
            )}
          </div>
        )}

        {/* ── Extract Text ──────────────────────────────────────────────── */}
        {nodeId === 'extract_text' && (
          <div className="space-y-1.5">
            {details.text_length != null && (
              <DetailRow label="Characters" value={details.text_length.toLocaleString()} />
            )}
            {details.estimated_page_count != null && (
              <DetailRow label="Estimated Pages" value={`${details.estimated_page_count}`} />
            )}
            {details.mime_type && <DetailRow label="Source Format" value={details.mime_type} />}
            {details.document_id && (
              <DetailRow label="Document" value={details.document_id.slice(0, 8) + '...'} />
            )}
            {details.extracted_text_preview && (
              <div className="mt-2 rounded-md bg-[#0a0d16] border border-white/[0.04] p-2 max-h-[200px] overflow-y-auto">
                <pre className="text-[11px] text-white/50 whitespace-pre-wrap font-mono leading-relaxed">
                  {details.extracted_text_preview.slice(0, 500)}
                  {details.extracted_text_preview.length > 500 ? '...' : ''}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* ── Classify ──────────────────────────────────────────────────── */}
        {nodeId === 'classify_document' && (
          <div className="space-y-1.5">
            {details.classification_label && (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wider text-white/30">Classification</span>
                <span className="text-[12px] text-white/90 font-semibold capitalize">{details.classification_label.replace(/_/g, ' ')}</span>
              </div>
            )}
            {details.classification_confidence != null && (
              <DetailRow label="Confidence" value={`${((details.classification_confidence ?? 0) * 100).toFixed(0)}%`} />
            )}
            {details.classification_method && (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wider text-white/30">Method</span>
                <MethodBadge method={details.classification_method} />
              </div>
            )}
            {details.classification_scores && (
              <div className="mt-2 space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Score Distribution</span>
                {Object.entries(details.classification_scores).map(([label, score]) => (
                  <div key={label} className="flex items-center gap-2">
                    <span className="text-[10px] text-white/40 w-36 truncate capitalize">{label.replace(/_/g, ' ')}</span>
                    <div className="flex-1 h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
                      <div
                        className="h-full rounded-full bg-indigo-500/60"
                        style={{ width: `${(score as number) * 100}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-white/40 font-mono w-8 text-right">{((score as number) * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Chunk ─────────────────────────────────────────────────────── */}
        {nodeId === 'chunk' && (
          <div className="space-y-1.5">
            <DetailRow label="Chunks" value={`${details.chunk_count ?? 0} segments`} />
            {details.chunk_max_size && <DetailRow label="Max Size" value={`${details.chunk_max_size} chars`} />}
            {details.chunk_overlap != null && <DetailRow label="Overlap" value={`${details.chunk_overlap} chars`} />}
            {details.chunks_preview && details.chunks_preview.length > 0 && (
              <div className="space-y-1 mt-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Chunk Boundaries</span>
                {details.chunks_preview.map((c: any) => (
                  <div key={c.index} className="rounded bg-[#0a0d16] border border-white/[0.04] px-2 py-1.5">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-[9px] text-white/30 font-mono">#{c.index}</span>
                      <span className="text-[9px] text-white/20">offset {c.start_offset}–{c.end_offset}</span>
                      <span className="text-[9px] text-white/20 ml-auto">{c.length} chars</span>
                    </div>
                    <p className="text-[10px] text-white/40 truncate">{c.text_preview}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Embed ─────────────────────────────────────────────────────── */}
        {nodeId === 'embed' && (
          <div className="space-y-1.5">
            <DetailRow label="Vectors Stored" value={`${details.vector_count ?? 0}`} />
            <DetailRow label="Model" value={details.embedding_model ?? 'none'} />
            <DetailRow label="Stored" value={details.embeddings_stored ? 'Yes' : 'No (skipped)'} />
          </div>
        )}

        {/* ── Extract Claims ────────────────────────────────────────────── */}
        {nodeId === 'extract_claims' && (
          <div className="space-y-1.5">
            <DetailRow label="Facts Extracted" value={`${details.claim_count ?? 0}`} />
            {details.extraction_method_counts && Object.keys(details.extraction_method_counts).length > 0 && (
              <div className="mt-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">By Extraction Method</span>
                <div className="mt-1 space-y-1">
                  {Object.entries(details.extraction_method_counts).map(([method, count]) => (
                    <div key={method} className="flex items-center justify-between">
                      <MethodBadge method={method} />
                      <span className="text-[11px] text-white/60 font-mono">{count as number}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {details.claims && details.claims.length > 0 && (
              <div className="space-y-1.5 mt-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Claims</span>
                {details.claims.slice(0, 8).map((claim: any) => (
                  <div key={claim.claim_id} className="rounded-md bg-[#0a0d16] border border-white/[0.04] px-2.5 py-2">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="text-[9px] font-mono text-indigo-300/60">{claim.claim_id}</span>
                      {claim._extraction_method && <MethodBadge method={claim._extraction_method} />}
                      <span className={`text-[9px] px-1 rounded ml-auto ${
                        claim.confidence >= 0.8 ? 'bg-emerald-500/20 text-emerald-300' :
                        claim.confidence >= 0.5 ? 'bg-amber-500/20 text-amber-300' :
                        'bg-rose-500/20 text-rose-300'
                      }`}>{((claim.confidence ?? 0) * 100).toFixed(0)}%</span>
                    </div>
                    <p className="text-[11px] text-white/60 leading-snug">{claim.claim_text}</p>
                  </div>
                ))}
                {details.claims.length > 8 && (
                  <p className="text-[10px] text-white/30 text-center">+{details.claims.length - 8} more claims</p>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Match Rules / Match Sources ───────────────────────────────── */}
        {(nodeId === 'match_rules' || nodeId === 'match_rules_against_sources') && (
          <div className="space-y-1.5">
            <DetailRow label="Findings" value={`${details.finding_count ?? 0}`} />
            {details.evaluation_method && (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wider text-white/30">Evaluation</span>
                <MethodBadge method={details.evaluation_method} />
              </div>
            )}
            {details.evaluation_method_counts && Object.keys(details.evaluation_method_counts).length > 0 && (
              <div className="mt-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Findings by Method</span>
                <div className="mt-1 space-y-1">
                  {Object.entries(details.evaluation_method_counts).map(([method, count]) => (
                    <div key={method} className="flex items-center justify-between">
                      <MethodBadge method={method} />
                      <span className="text-[11px] text-white/60 font-mono">{count as number}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {details.verdict_counts && Object.keys(details.verdict_counts).length > 0 && (
              <div className="mt-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Verdict Summary</span>
                <div className="mt-1 flex flex-wrap gap-2">
                  {Object.entries(details.verdict_counts).map(([verdict, count]) => (
                    <span key={verdict} className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium border ${
                      verdict === 'compliant' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' :
                      verdict === 'non_compliant' ? 'bg-rose-500/15 text-rose-300 border-rose-500/30' :
                      'bg-amber-500/15 text-amber-300 border-amber-500/30'
                    }`}>
                      {verdict.replace(/_/g, ' ')} <span className="font-mono">{count as number}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            {details.verdicts && details.verdicts.length > 0 && (
              <div className="space-y-1.5 mt-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Verdicts</span>
                {details.verdicts.slice(0, 8).map((v: any, i: number) => (
                  <div key={i} className="rounded-md bg-[#0a0d16] border border-white/[0.04] px-2.5 py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[9px] font-mono text-white/40">{v.claim_id}</span>
                      <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold uppercase ${
                        v.verdict === 'compliant' ? 'bg-emerald-500/20 text-emerald-300' :
                        v.verdict === 'non_compliant' ? 'bg-rose-500/20 text-rose-300' :
                        'bg-amber-500/20 text-amber-300'
                      }`}>{v.verdict}</span>
                      {v.rule_id && <span className="text-[9px] text-indigo-300/60">{v.rule_id}</span>}
                    </div>
                    {v.reason && <p className="text-[10px] text-white/40 mt-0.5">{v.reason}</p>}
                  </div>
                ))}
                {details.verdicts.length > 8 && (
                  <p className="text-[10px] text-white/30 text-center">+{details.verdicts.length - 8} more</p>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Merge Findings ────────────────────────────────────────────── */}
        {nodeId === 'merge_findings' && (
          <div className="space-y-1.5">
            <DetailRow label="Merged Findings" value={`${details.finding_count ?? 0}`} />
            {details.findings && details.findings.length > 0 && (
              <div className="space-y-1 mt-1.5">
                {details.findings.slice(0, 6).map((f: any, i: number) => (
                  <div key={i} className="rounded-md bg-[#0a0d16] border border-white/[0.04] px-2.5 py-2">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      {f.severity && (
                        <span className={`text-[9px] px-1 rounded font-bold uppercase ${
                          f.severity === 'high' ? 'bg-rose-500/20 text-rose-300' :
                          f.severity === 'medium' ? 'bg-amber-500/20 text-amber-300' :
                          'bg-white/10 text-white/50'
                        }`}>{f.severity}</span>
                      )}
                      {f.rule_id && <span className="text-[9px] text-indigo-300/60">{f.rule_id}</span>}
                    </div>
                    <p className="text-[11px] text-white/60">{f.description || f.reason || '—'}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Score Confidence ──────────────────────────────────────────── */}
        {nodeId === 'score_confidence' && (
          <div className="space-y-1.5">
            <DetailRow label="Verdicts Scored" value={`${(details.verdicts ?? []).length}`} />
            {details.verdicts && details.verdicts.length > 0 && (
              <div className="space-y-1 mt-1.5">
                {details.verdicts.slice(0, 6).map((v: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 px-2 py-1 rounded bg-[#0a0d16] border border-white/[0.04]">
                    <span className="text-[9px] font-mono text-white/40">{v.claim_id}</span>
                    <span className={`text-[9px] px-1 rounded ${
                      v.confidence >= 0.8 ? 'bg-emerald-500/20 text-emerald-300' :
                      v.confidence >= 0.5 ? 'bg-amber-500/20 text-amber-300' :
                      'bg-rose-500/20 text-rose-300'
                    }`}>{((v.confidence ?? 0) * 100).toFixed(0)}%</span>
                    {v.needs_human_review && <span className="text-[9px] text-amber-300/60">needs review</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Route to Queue ────────────────────────────────────────────── */}
        {nodeId === 'route_to_queue' && (
          <div className="space-y-1.5">
            <DetailRow label="Auto-approve" value={`${details.auto_approve_count ?? 0} claims`} />
            <DetailRow label="Escalated" value={`${details.escalate_count ?? 0} claims`} />
            <DetailRow label="Auto-reject" value={`${details.auto_reject_count ?? 0} claims`} />
            {details.confidence_threshold != null && (
              <DetailRow label="Threshold" value={`${(details.confidence_threshold * 100).toFixed(0)}%`} />
            )}
            {details.routing_reasons && details.routing_reasons.length > 0 && (
              <div className="mt-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Escalation Reasons</span>
                <div className="mt-1 space-y-1">
                  {details.routing_reasons.slice(0, 8).map((r: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 px-2 py-1 rounded bg-[#0a0d16] border border-white/[0.04]">
                      <span className="text-[9px] font-mono text-white/40">{r.claim_id}</span>
                      <span className="text-[10px] text-amber-200/70">{r.reason?.replace(/_/g, ' ')}</span>
                    </div>
                  ))}
                  {details.routing_reasons.length > 8 && (
                    <p className="text-[10px] text-white/30 text-center">+{details.routing_reasons.length - 8} more</p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Human Review ──────────────────────────────────────────────── */}
        {nodeId === 'human_review' && (
          <div className="space-y-1.5">
            <DetailRow label="Decisions Made" value={`${details.decision_count ?? 0}`} />
            {details.decisions && details.decisions.length > 0 && (
              <div className="space-y-1 mt-1.5">
                {details.decisions.slice(0, 6).map((d: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 px-2 py-1 rounded bg-[#0a0d16] border border-white/[0.04]">
                    <span className="text-[9px] font-mono text-white/40">{d.claim_id}</span>
                    <span className={`text-[9px] px-1.5 rounded font-bold uppercase ${
                      d.decision_value === 'approved' ? 'bg-emerald-500/20 text-emerald-300' :
                      'bg-rose-500/20 text-rose-300'
                    }`}>{d.decision_value}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Finalize ──────────────────────────────────────────────────── */}
        {nodeId === 'finalize' && (
          <div className="space-y-1.5">
            <DetailRow label="Total Claims" value={`${details.total_claims ?? 0}`} />
            <DetailRow label="Total Findings" value={`${details.total_findings ?? 0}`} />
          </div>
        )}
      </div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[10px] uppercase tracking-wider text-white/30">{label}</span>
      <span className="text-[11px] text-white/70 font-medium">{value}</span>
    </div>
  );
}

// ─── Main Panel ──────────────────────────────────────────────────────────────

interface NodeDetailPanelProps {
  nodeId: string | null;
  nodeLabel: string;
  onClose: () => void;
  runId?: string | null;
}

export function NodeDetailPanel({ nodeId, nodeLabel, onClose, runId }: NodeDetailPanelProps) {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [nodeDetails, setNodeDetails] = useState<any>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  // Fetch node execution details from the backend
  useEffect(() => {
    if (!nodeId || !runId) {
      setNodeDetails(null);
      return;
    }
    setDetailsLoading(true);

    async function fetchDetails() {
      try {
        const res = await fetch(`${BASE_URL}/runs/${runId}/node/${nodeId}/details`);
        if (res.ok) {
          const data = await res.json();
          setNodeDetails(data);
        } else {
          setNodeDetails(null);
        }
      } catch {
        setNodeDetails(null);
      }
      setDetailsLoading(false);
    }

    fetchDetails();
  }, [nodeId, runId]);

  // Fetch items for this node (approval queue items relevant to the clicked node)
  useEffect(() => {
    if (!nodeId) return;
    setLoading(true);

    async function fetchItems() {
      if (USE_MOCK) {
        await new Promise((r) => setTimeout(r, 200));
        setItems(MOCK_NODE_ITEMS[nodeId!] ?? []);
      } else {
        if (!runId) {
          setItems([]);
          setLoading(false);
          return;
        }

        // Only fetch approval queue items for nodes in the stay-alive stage
        // (route_to_queue, human_review, finalize) where approval items exist.
        const approvalNodes = ['route_to_queue', 'human_review', 'finalize', 'score_confidence'];
        if (!approvalNodes.includes(nodeId!)) {
          setItems([]);
          setLoading(false);
          return;
        }

        try {
          const res = await fetch(`${BASE_URL}/approval/runs/${runId}/queue`);
          if (res.ok) {
            const data = await res.json();
            setItems(data.items ?? []);
          } else {
            setItems([]);
          }
        } catch {
          setItems([]);
        }
      }
      setLoading(false);
    }

    fetchItems();
  }, [nodeId, runId]);

  // Handle decision — only updates the single item
  const handleDecision = useCallback(async (itemId: string, decision: 'approved' | 'rejected') => {
    if (USE_MOCK) {
      await new Promise((r) => setTimeout(r, 400));
      setItems((prev) => prev.map((item) =>
        item.id === itemId
          ? { ...item, status: decision, decision, decided_at: new Date().toISOString(), reviewer_id: 'current-user' }
          : item
      ));
    } else {
      try {
        await fetch(`${BASE_URL}/approval/items/${itemId}/decide`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ decision, reviewer_id: 'current-user', justification: `${decision} via pipeline canvas` }),
        });
        // Update only this item locally
        setItems((prev) => prev.map((item) =>
          item.id === itemId
            ? { ...item, status: decision, decision, decided_at: new Date().toISOString(), reviewer_id: 'current-user' }
            : item
        ));
      } catch {
        // Keep original state on failure
      }
    }
  }, []);

  const isOpen = nodeId !== null;
  const pendingCount = items.filter((i) => i.status === 'pending').length;
  const totalCount = items.length;

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div className="absolute inset-0 bg-black/20 z-10" onClick={onClose} />
      )}

      {/* Panel */}
      <div
        className={`absolute top-0 right-0 h-full w-[420px] max-w-[90vw] z-20 bg-[#0c0f1a] border-l border-white/[0.06] shadow-2xl shadow-black/50 transform transition-transform duration-250 ease-out ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {isOpen && (
          <div className="flex flex-col h-full">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
              <div>
                <h2 className="text-sm font-semibold text-white/90">{nodeLabel}</h2>
                <p className="text-[11px] text-white/40 mt-0.5">
                  {totalCount === 0 ? 'No items' : `${pendingCount} pending · ${totalCount} total`}
                </p>
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

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-3 space-y-3">
              {/* Node execution details */}
              {nodeDetails && !detailsLoading && (
                <NodeDetailsSection details={nodeDetails} />
              )}
              {detailsLoading && (
                <div className="rounded-lg border border-white/[0.06] bg-[#141927]/60 p-3">
                  <div className="flex items-center gap-2 text-xs text-white/40">
                    <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                      <circle cx="12" cy="12" r="10" opacity={0.25} />
                      <path d="M4 12a8 8 0 018-8" opacity={0.75} />
                    </svg>
                    Loading node details...
                  </div>
                </div>
              )}

              {loading && (
                <div className="flex items-center justify-center py-12">
                  <svg className="w-5 h-5 text-indigo-400 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <circle cx="12" cy="12" r="10" opacity={0.25} />
                    <path d="M4 12a8 8 0 018-8" opacity={0.75} />
                  </svg>
                </div>
              )}

              {!loading && items.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <svg className="w-8 h-8 text-white/20 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1}>
                    <rect x="3" y="3" width="18" height="18" rx="3" />
                    <path d="M9 12h6M12 9v6" />
                  </svg>
                  <p className="text-xs text-white/30">No findings or items at this stage</p>
                </div>
              )}

              {!loading && items.map((item) => (
                <ItemCard key={item.id} item={item} onDecision={handleDecision} />
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

export default NodeDetailPanel;
