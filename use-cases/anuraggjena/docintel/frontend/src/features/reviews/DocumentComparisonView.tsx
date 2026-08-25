import { useMemo, useState } from 'react'
import { Sparkles, Columns, ChevronDown, ChevronUp } from 'lucide-react'
import { DiffText } from '@/shared/components/DiffText'
import { TechnicalDetails } from '@/shared/components/TechnicalDetails'
import { buildParagraphDiffs } from './buildDocumentDiff'
import type { ParsedReviewClaim } from './superdocsClaim'

export interface DocumentComparisonViewProps {
  claim: ParsedReviewClaim
}

export function DocumentComparisonView({ claim }: DocumentComparisonViewProps) {
  const [activeTab, setActiveTab] = useState<'preview' | 'explanation'>('preview')
  const [viewMode, setViewMode] = useState<'side-by-side' | 'unified'>('side-by-side')
  const [showUnchanged, setShowUnchanged] = useState(true)

  const paragraphDiffs = useMemo(() => {
    return buildParagraphDiffs(claim.oldHtml || claim.oldText, claim.newHtml || claim.newText)
  }, [claim.oldHtml, claim.oldText, claim.newHtml, claim.newText])

  const visibleParagraphs = useMemo(() => {
    if (showUnchanged) return paragraphDiffs
    return paragraphDiffs.filter((p) => p.hasChanges)
  }, [paragraphDiffs, showUnchanged])

  const technicalJson = useMemo(() => {
    return JSON.stringify(
      {
        id: claim.id,
        change_id: claim.changeId,
        chunk_id: claim.chunkId,
        section: claim.section,
        page: claim.page,
        status: claim.status,
        raw_payload: claim.rawPayload || claim.rawContent,
      },
      null,
      2
    )
  }, [claim])

  return (
    <div className="flex flex-col rounded-xl border border-border bg-card shadow-xs overflow-hidden">
      {/* Top Tabs & Mode Switcher */}
      <div className="flex flex-col gap-3 border-b border-border bg-muted/20 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setActiveTab('preview')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer ${
              activeTab === 'preview'
                ? 'bg-background text-foreground shadow-xs'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Preview changes
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('explanation')}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer ${
              activeTab === 'explanation'
                ? 'bg-background text-foreground shadow-xs'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Sparkles className="h-3.5 w-3.5 text-blue-600" />
            AI explanation
          </button>
        </div>

        <div className="flex items-center gap-4">
          {/* Legend */}
          <div className="hidden sm:flex items-center gap-3 text-xs font-medium">
            <span className="inline-flex items-center gap-1.5 text-emerald-800">
              <span className="h-2 w-2 rounded-full bg-emerald-500" /> Added
            </span>
            <span className="inline-flex items-center gap-1.5 text-rose-800">
              <span className="h-2 w-2 rounded-full bg-rose-500" /> Removed
            </span>
            <span className="inline-flex items-center gap-1.5 text-amber-800">
              <span className="h-2 w-2 rounded-full bg-amber-500" /> Modified
            </span>
          </div>

          {/* View toggle */}
          {activeTab === 'preview' && (
            <button
              type="button"
              onClick={() => setViewMode((m) => (m === 'side-by-side' ? 'unified' : 'side-by-side'))}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground bg-muted/50 hover:bg-muted rounded-lg transition-colors cursor-pointer"
            >
              <Columns className="h-3.5 w-3.5" />
              <span>{viewMode === 'side-by-side' ? 'View: Side-by-side' : 'View: Unified'}</span>
            </button>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="p-5 sm:p-6 space-y-6">
        {activeTab === 'preview' ? (
          <>
            {viewMode === 'side-by-side' ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                {/* Original (Current) Box */}
                <div className="flex flex-col rounded-xl border border-rose-200/60 bg-rose-50/20 overflow-hidden">
                  <div className="border-b border-rose-200/50 bg-rose-50/50 px-4 py-2.5 flex items-center justify-between">
                    <div>
                      <span className="text-xs font-bold text-rose-900 uppercase tracking-wider">
                        Original (Current)
                      </span>
                      <p className="text-[11px] text-rose-700/80 mt-0.5">
                        {claim.section} • {claim.page}
                      </p>
                    </div>
                  </div>
                  <div className="p-4 space-y-4 max-h-[500px] overflow-y-auto leading-relaxed">
                    {!claim.oldHtml && !claim.oldText ? (
                      <div className="py-8 text-center text-xs font-medium text-muted-foreground italic">
                        New content — no prior version exists
                      </div>
                    ) : (
                      visibleParagraphs.map((para, i) => (
                        <p key={i} className="text-sm font-serif leading-relaxed text-slate-800">
                          {para.originalTokens.length > 0 ? (
                            <DiffText tokens={para.originalTokens} />
                          ) : (
                            <span className="text-xs text-muted-foreground italic">(No content)</span>
                          )}
                        </p>
                      ))
                    )}
                  </div>
                </div>

                {/* Proposed (New) Box */}
                <div className="flex flex-col rounded-xl border border-emerald-200/60 bg-emerald-50/20 overflow-hidden">
                  <div className="border-b border-emerald-200/50 bg-emerald-50/50 px-4 py-2.5 flex items-center justify-between">
                    <div>
                      <span className="text-xs font-bold text-emerald-900 uppercase tracking-wider">
                        Proposed (New)
                      </span>
                      <p className="text-[11px] text-emerald-700/80 mt-0.5">
                        {claim.section} • {claim.page}
                      </p>
                    </div>
                  </div>
                  <div className="p-4 space-y-4 max-h-[500px] overflow-y-auto leading-relaxed">
                    {!claim.newHtml && !claim.newText ? (
                      <div className="py-8 text-center text-xs font-medium text-muted-foreground italic">
                        Content proposed for removal
                      </div>
                    ) : (
                      visibleParagraphs.map((para, i) => (
                        <p key={i} className="text-sm font-serif leading-relaxed text-slate-800">
                          {para.proposedTokens.length > 0 ? (
                            <DiffText tokens={para.proposedTokens} />
                          ) : (
                            <span className="text-xs text-muted-foreground italic">(Content removed)</span>
                          )}
                        </p>
                      ))
                    )}
                  </div>
                </div>
              </div>
            ) : (
              /* Unified View */
              <div className="rounded-xl border border-border bg-background p-5 space-y-4 max-h-[500px] overflow-y-auto">
                <div className="border-b pb-2 flex items-center justify-between">
                  <span className="text-xs font-bold text-foreground uppercase tracking-wider">
                    {claim.section} • {claim.page}
                  </span>
                </div>
                {visibleParagraphs.map((para, i) => (
                  <p key={i} className="text-sm font-serif leading-relaxed">
                    <DiffText tokens={[...para.originalTokens.filter((t) => t.type === 'delete'), ...para.proposedTokens]} />
                  </p>
                ))}
              </div>
            )}

            {/* Unchanged Content Toggle */}
            {paragraphDiffs.some((p) => !p.hasChanges) && (
              <div className="flex justify-center">
                <button
                  type="button"
                  onClick={() => setShowUnchanged((v) => !v)}
                  className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground cursor-pointer"
                >
                  {showUnchanged ? (
                    <>
                      <ChevronUp className="h-3.5 w-3.5" /> Hide unchanged content
                    </>
                  ) : (
                    <>
                      <ChevronDown className="h-3.5 w-3.5" /> Show unchanged content
                    </>
                  )}
                </button>
              </div>
            )}
          </>
        ) : null}

        {/* AI Explanation Card (always shown or highlighted when AI explanation tab is active) */}
        {claim.aiExplanation && (
          <div className="rounded-xl border border-blue-200/70 bg-blue-50/40 p-4 sm:p-5 space-y-2.5">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-blue-600" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-blue-900">
                Why this change is proposed
              </h3>
            </div>
            <p className="text-xs sm:text-sm font-medium leading-relaxed text-blue-950">
              {claim.aiExplanation}
            </p>

            <div className="pt-2">
              <TechnicalDetails copyText={technicalJson} label="View technical details">
                {technicalJson}
              </TechnicalDetails>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
