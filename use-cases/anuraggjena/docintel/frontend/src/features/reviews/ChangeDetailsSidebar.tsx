import { useState } from 'react'
import { Copy, Check, FileText } from 'lucide-react'
import { StatusBadge } from '@/shared/components/StatusBadge'
import type { ParsedReviewClaim } from './superdocsClaim'

export interface ChangeDetailsSidebarProps {
  claim: ParsedReviewClaim
  reviewId: string
  requestedAt: string
  documentName?: string
}

function formatDetailDate(iso: string): string {
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    const datePart = d.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
    const timePart = d.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    })
    return `${datePart} at ${timePart}`
  } catch {
    return iso
  }
}

export function ChangeDetailsSidebar({
  claim,
  reviewId,
  requestedAt,
  documentName,
}: ChangeDetailsSidebarProps) {
  const [copiedReviewId, setCopiedReviewId] = useState(false)

  const handleCopyReviewId = () => {
    navigator.clipboard.writeText(reviewId)
    setCopiedReviewId(true)
    setTimeout(() => setCopiedReviewId(false), 2000)
  }

  const effectiveDocName =
    claim.documentName ||
    documentName ||
    'classification_ruling.pdf'

  const formattedReviewId = `rev_${reviewId.replace(/-/g, '').slice(0, 12)}...`

  return (
    <div className="flex flex-col rounded-xl border border-border bg-card shadow-xs p-5 space-y-5">
      <div className="flex items-center justify-between pb-3 border-b border-border">
        <h2 className="text-sm font-semibold text-foreground">Change details</h2>
        <StatusBadge status={claim.status} type="claim" />
      </div>

      <div className="space-y-4">
        {/* SECTION */}
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Section
          </p>
          <p className="text-xs font-semibold text-foreground">{claim.section}</p>
        </div>

        {/* CHANGE TYPE */}
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Change Type
          </p>
          <div>
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${
                claim.changeType === 'added'
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : claim.changeType === 'removed'
                    ? 'bg-rose-50 text-rose-700 border-rose-200'
                    : 'bg-amber-50 text-amber-700 border-amber-200'
              }`}
            >
              {claim.changeType === 'added'
                ? '+ Added'
                : claim.changeType === 'removed'
                  ? '- Removed'
                  : '✏ Modified'}
            </span>
          </div>
        </div>

        {/* DOCUMENT */}
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Document
          </p>
          <div className="flex items-center gap-1.5 text-xs text-foreground font-medium">
            <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <span className="truncate" title={effectiveDocName}>
              {effectiveDocName}
            </span>
          </div>
        </div>

        {/* PAGE */}
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Page
          </p>
          <p className="text-xs text-foreground font-medium">{claim.page.replace(/Page\s*/i, '')}</p>
        </div>

        {/* REQUESTED AT */}
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Requested at
          </p>
          <p className="text-xs text-foreground font-medium">{formatDetailDate(requestedAt)}</p>
        </div>

        {/* REVIEW ID */}
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Review ID
          </p>
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs text-muted-foreground" title={reviewId}>
              {formattedReviewId}
            </span>
            <button
              type="button"
              onClick={handleCopyReviewId}
              className="text-muted-foreground hover:text-foreground transition-colors p-0.5 rounded"
              title="Copy Review ID"
            >
              {copiedReviewId ? (
                <Check className="h-3.5 w-3.5 text-emerald-600" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        </div>

        {/* LENGTH COMPARISON */}
        <div className="pt-2 border-t border-border space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground font-medium">Original length</span>
            <span className="font-mono text-foreground font-semibold">
              {claim.originalLength.toLocaleString()} characters
            </span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground font-medium">Proposed length</span>
            <span className="font-mono text-foreground font-semibold">
              {claim.proposedLength.toLocaleString()} characters
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
