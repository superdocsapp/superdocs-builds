import { ArrowLeft, ArrowRight, Check, X, Lock, Play } from 'lucide-react'
import { Button } from '@/shared/components/ui/button'
import type { ParsedReviewClaim } from './superdocsClaim'

export interface ReviewActionBarProps {
  currentIndex: number
  totalChanges: number
  activeClaim: ParsedReviewClaim
  canDecide: boolean
  isApproving: boolean
  isRejecting: boolean
  isResuming?: boolean
  showResumeWorkflow?: boolean
  onPrevious: () => void
  onNext: () => void
  onApprove: () => void
  onReject: () => void
  onResumeWorkflow?: () => void
}

export function ReviewActionBar({
  currentIndex,
  totalChanges,
  activeClaim,
  canDecide,
  isApproving,
  isRejecting,
  isResuming = false,
  showResumeWorkflow = false,
  onPrevious,
  onNext,
  onApprove,
  onReject,
  onResumeWorkflow,
}: ReviewActionBarProps) {
  const isPending =
    activeClaim.status !== 'approved' &&
    activeClaim.status !== 'rejected' &&
    activeClaim.status !== 'applied' &&
    activeClaim.status !== 'rejected_applied'

  const hasPrevious = currentIndex > 0
  const hasNext = currentIndex < totalChanges - 1

  return (
    <div className="flex flex-col items-center gap-3 pt-6 pb-8">
      <div className="flex w-full flex-col gap-4 rounded-xl border border-border bg-card p-4 shadow-xs sm:flex-row sm:items-center sm:justify-between">
        {/* Navigation buttons */}
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onPrevious}
            disabled={!hasPrevious}
            className="gap-1.5 text-xs cursor-pointer"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Previous change
          </Button>

          <span className="text-xs font-semibold text-muted-foreground px-2">
            Change {currentIndex + 1} of {totalChanges}
          </span>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onNext}
            disabled={!hasNext}
            className="gap-1.5 text-xs cursor-pointer"
          >
            Next change
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-3">
          {isPending ? (
            canDecide ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={onReject}
                  disabled={isApproving || isRejecting}
                  className="gap-1.5 text-xs font-medium border-rose-300 text-rose-700 hover:bg-rose-50 hover:text-rose-800 hover:border-rose-400 cursor-pointer"
                >
                  <X className="h-3.5 w-3.5 text-rose-600" />
                  {isRejecting ? 'Rejecting…' : 'Reject change'}
                </Button>

                <Button
                  type="button"
                  size="sm"
                  onClick={onApprove}
                  disabled={isApproving || isRejecting}
                  className="gap-1.5 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs cursor-pointer"
                >
                  <Check className="h-3.5 w-3.5" />
                  {isApproving ? 'Approving…' : 'Approve change'}
                </Button>
              </>
            ) : (
              <span className="text-xs text-muted-foreground italic">
                Read-only access
              </span>
            )
          ) : (
            <div className="flex items-center gap-3">
              {activeClaim.status === 'approved' || activeClaim.status === 'applied' ? (
                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                  <Check className="h-3.5 w-3.5" /> Change Approved
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200">
                  <X className="h-3.5 w-3.5" /> Change Rejected
                </span>
              )}

              {showResumeWorkflow && onResumeWorkflow && (
                <Button
                  type="button"
                  size="sm"
                  onClick={onResumeWorkflow}
                  disabled={isResuming}
                  className="gap-1.5 text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white shadow-xs cursor-pointer"
                >
                  <Play className="h-3.5 w-3.5" />
                  {isResuming ? 'Resuming…' : 'Resume Workflow'}
                </Button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Compliance / Audit caption */}
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Lock className="h-3.5 w-3.5" />
        <span>Your decision will be recorded in the audit trail.</span>
      </div>
    </div>
  )
}
