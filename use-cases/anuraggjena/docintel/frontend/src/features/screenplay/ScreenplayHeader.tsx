import { CheckCircle2, Loader2 } from 'lucide-react'
import { ExportDropdown } from '@/features/exports/ExportDropdown'

interface ScreenplayHeaderProps {
  title: string
  statusBadge?: string
  pagesCount: number
  lastSavedText?: string
  workspaceId: string
  runId?: string
  runStatus?: string
  pendingReviewCount: number
  onReviewClick?: () => void
}

export function ScreenplayHeader({
  title,
  statusBadge = 'Draft',
  pagesCount,
  lastSavedText = 'Last saved just now',
  workspaceId,
  runId,
  runStatus,
  pendingReviewCount,
  onReviewClick,
}: ScreenplayHeaderProps) {
  const isReadyForReview = pendingReviewCount > 0 || runStatus === 'waiting' || runStatus === 'awaiting_review'
  const isCompleted = runStatus === 'completed'

  return (
    <div className="space-y-2">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        {/* Left: Title, Draft Badge, Subtitle */}
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
              {title}
            </h1>
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-slate-100 text-slate-600 border border-slate-200/80">
              {statusBadge}
            </span>
          </div>

          <p className="text-xs text-slate-500 font-medium">
            <span>{lastSavedText}</span>
            <span className="mx-2 text-slate-300">•</span>
            <span>{pagesCount} {pagesCount === 1 ? 'page' : 'pages'}</span>
            <span className="mx-2 text-slate-300">•</span>
            <span className="text-slate-600">Screenplay</span>
          </p>
        </div>

        {/* Right: Status Pill & Export Dropdown */}
        <div className="flex items-center gap-3 shrink-0">
          {/* Status Indicator */}
          {isReadyForReview ? (
            <button
              type="button"
              onClick={onReviewClick}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200/80 hover:bg-emerald-100 transition-colors cursor-pointer"
            >
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
              <span>Ready for review</span>
            </button>
          ) : isCompleted ? (
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200/80">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
              <span>Formatting complete</span>
            </span>
          ) : runStatus === 'running' ? (
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200/80">
              <Loader2 className="w-3.5 h-3.5 text-blue-600 animate-spin" />
              <span>Formatting in progress…</span>
            </span>
          ) : null}

          {/* Export [ PDF | DOCX ] Dropdown */}
          {runId && (
            <ExportDropdown
              workspaceId={workspaceId}
              runId={runId}
              workflowSlug="screenplay"
              variant="primary"
              size="sm"
            />
          )}
        </div>
      </div>
    </div>
  )
}

