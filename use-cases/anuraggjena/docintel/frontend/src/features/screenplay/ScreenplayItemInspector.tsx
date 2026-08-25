import { useState } from 'react'
import type { FormattingItem } from '@/core/api/screenplayApi'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Button } from '@/shared/components/ui/button'
import { Check, X, Sparkles } from 'lucide-react'

export interface ScreenplayItemInspectorProps {
  item: FormattingItem
  onApprove: (itemId: string) => void
  onReject: (itemId: string, comment?: string) => void
  isApproving?: boolean
  isRejecting?: boolean
}

export function ScreenplayItemInspector({
  item,
  onApprove,
  onReject,
  isApproving = false,
  isRejecting = false,
}: ScreenplayItemInspectorProps) {
  const [comment, setComment] = useState('')
  const [showRejectInput, setShowRejectInput] = useState(false)

  const estimatedPage = item.element_index ? Math.max(1, Math.ceil((item.element_index + 1) / 45)) : 1
  const line = (item.element_index ?? 0) + 1

  return (
    <div className="flex h-full w-full flex-col bg-card">
      {/* Header */}
      <div className="border-b px-4 py-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-foreground">Change details</h2>
      </div>

      <div className="space-y-5 p-4 text-xs">
        {/* Metadata Grid */}
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-lg border bg-muted/40 p-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Element type
            </span>
            <p className="mt-0.5 font-mono text-xs font-medium text-foreground">
              {item.element_type.toUpperCase()}
            </p>
          </div>
          <div className="rounded-lg border bg-muted/40 p-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Location
            </span>
            <p className="mt-0.5 font-mono text-xs font-medium text-foreground">
              Line {line} {item.scene_number !== null ? `(Scene ${item.scene_number})` : ''} · Page {estimatedPage}
            </p>
          </div>
          <div className="rounded-lg border bg-muted/40 p-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Change category
            </span>
            <p className="mt-0.5 font-mono text-xs font-medium text-foreground">
              {item.change_type.replace(/_/g, ' ')}
            </p>
          </div>
          <div className="rounded-lg border bg-muted/40 p-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Status
            </span>
            <div className="mt-0.5">
              <StatusBadge status={item.status} type="claim" />
            </div>
          </div>
        </div>

        {/* Change Reason */}
        {item.reason && (
          <div className="rounded-lg border border-amber-200/80 bg-amber-50/50 p-3 text-xs dark:border-amber-900/40 dark:bg-amber-950/20">
            <div className="flex items-center gap-1.5 font-semibold text-amber-800 dark:text-amber-300">
              <Sparkles className="h-3.5 w-3.5" />
              <span>Formatting Rule Applied</span>
            </div>
            <p className="mt-1 text-slate-700 leading-relaxed dark:text-slate-300">{item.reason}</p>
          </div>
        )}

        {/* Diff Side-by-Side */}
        <div className="space-y-3">
          <div className="space-y-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-rose-600 dark:text-rose-400">
              Original text
            </span>
            <div className="rounded-md border border-rose-200 bg-rose-50/50 p-2.5 font-mono text-xs leading-relaxed text-rose-950 whitespace-pre-wrap dark:border-rose-950 dark:bg-rose-950/20 dark:text-rose-200">
              {item.original_text || <span className="italic text-muted-foreground">Empty</span>}
            </div>
          </div>

          <div className="space-y-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
              Proposed formatting
            </span>
            <div className="rounded-md border border-emerald-200 bg-emerald-50/50 p-2.5 font-mono text-xs leading-relaxed text-emerald-950 whitespace-pre-wrap dark:border-emerald-950 dark:bg-emerald-950/20 dark:text-emerald-200">
              {item.formatted_text || <span className="italic text-muted-foreground">Empty</span>}
            </div>
          </div>
        </div>

        {/* Diff Tokens View if available */}
        {item.diff_tokens && item.diff_tokens.length > 0 && (
          <div className="space-y-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Inline diff preview
            </span>
            <div className="rounded-md border bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-100 dark:bg-slate-950">
              {item.diff_tokens.map((token, idx) => {
                if (token.type === 'delete') {
                  return (
                    <span key={idx} className="bg-rose-800/80 text-rose-200 line-through px-0.5 rounded">
                      {token.text}
                    </span>
                  )
                }
                if (token.type === 'insert') {
                  return (
                    <span key={idx} className="bg-emerald-700/80 text-emerald-100 font-bold px-0.5 rounded">
                      {token.text}
                    </span>
                  )
                }
                return <span key={idx}>{token.text}</span>
              })}
            </div>
          </div>
        )}

        {/* Reviewer Comment if exists */}
        {item.reviewer_comment && (
          <div className="rounded-lg border bg-muted/40 p-3">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Reviewer feedback
            </span>
            <p className="mt-1 font-mono text-xs text-foreground">{item.reviewer_comment}</p>
          </div>
        )}
      </div>

      {/* Action Footer */}
      <div className="shrink-0 border-t bg-card p-4">
        {item.status === 'approved' ? (
          <div className="flex items-center justify-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50/80 p-2.5 text-xs font-semibold text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-300">
            <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            <span>Approved</span>
          </div>
        ) : item.status === 'rejected' ? (
          <div className="flex items-center justify-center gap-2 rounded-lg border border-rose-200 bg-rose-50/80 p-2.5 text-xs font-semibold text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-300">
            <X className="h-4 w-4 text-rose-600 dark:text-rose-400" />
            <span>Rejected</span>
          </div>
        ) : showRejectInput ? (
          <div className="space-y-2">
            <input
              type="text"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Reason for rejection (optional)"
              className="w-full rounded-md border bg-background px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <div className="flex gap-2">
              <Button
                type="button"
                variant="destructive"
                size="sm"
                className="flex-1 text-xs"
                disabled={isRejecting}
                onClick={() => {
                  onReject(item.id, comment || undefined)
                  setShowRejectInput(false)
                  setComment('')
                }}
              >
                {isRejecting ? 'Rejecting…' : 'Confirm reject'}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="text-xs"
                onClick={() => {
                  setShowRejectInput(false)
                  setComment('')
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="flex-1 border-rose-200 text-rose-700 hover:bg-rose-50 hover:text-rose-800 dark:border-rose-900 dark:text-rose-400 dark:hover:bg-rose-950/40 text-xs"
              disabled={isRejecting}
              onClick={() => setShowRejectInput(true)}
            >
              <X className="mr-1.5 h-3.5 w-3.5" />
              Reject change
            </Button>
            <Button
              type="button"
              size="sm"
              className="flex-1 bg-emerald-600 text-white hover:bg-emerald-700 dark:bg-emerald-600 dark:hover:bg-emerald-700 text-xs"
              disabled={isApproving}
              onClick={() => onApprove(item.id)}
            >
              <Check className="mr-1.5 h-3.5 w-3.5" />
              {isApproving ? 'Approving…' : 'Approve change'}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
