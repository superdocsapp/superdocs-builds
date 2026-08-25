import { useEffect, useMemo, useRef } from 'react'
import { Check, Clock, AlertCircle, X, Loader2 } from 'lucide-react'
import type { WorkflowStage } from '@/core/api/types'
import { formatStageName } from '@/core/labels'
import { cn } from '@/lib/utils'

function formatDuration(ms: number | null): string | null {
  if (ms == null) return null
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
}

function formatTime(iso: string | null): string {
  if (!iso) return ''
  const normalized = iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z'
  const d = new Date(normalized)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true })
}

interface StageTimelineProps {
  stages: WorkflowStage[]
  currentStageName?: string | null
  className?: string
}

export function StageTimeline({ stages, currentStageName, className }: StageTimelineProps) {
  const activeRef = useRef<HTMLLIElement | null>(null)

  // Scroll the running stage into view whenever it changes
  useEffect(() => {
    if (activeRef.current) {
      activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [currentStageName, stages.length])

  const stats = useMemo(() => {
    const completed = stages.filter((s) => s.status === 'completed').length
    const issues = stages.filter((s) => s.status === 'failed' || s.status === 'blocked').length
    return { completed, issues }
  }, [stages])

  if (stages.length === 0) {
    return (
      <div className={cn("bg-white border border-slate-200/90 rounded-2xl p-6 shadow-xs", className)}>
        <h3 className="text-sm font-bold text-slate-900 mb-2">Stage Timeline</h3>
        <p className="text-xs text-slate-400">No stages recorded for this run yet.</p>
      </div>
    )
  }

  return (
    <div className={cn("bg-white border border-slate-200/90 rounded-2xl p-5 sm:p-6 shadow-xs space-y-5", className)}>
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-100">
        <h3 className="text-sm font-bold text-slate-900 tracking-tight">Stage Timeline</h3>
        <div className="flex items-center gap-3 text-xs">
          <span className="font-semibold text-emerald-600">
            {stats.completed} completed
          </span>
          <span className={cn('font-semibold', stats.issues > 0 ? 'text-amber-600' : 'text-emerald-600')}>
            {stats.issues} issue{stats.issues !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {/* Vertical Timeline List */}
      <ol className="relative ml-16 space-y-5">
        {/* Continuous vertical line */}
        <div className="absolute left-0 top-2 bottom-2 w-px bg-slate-200 -translate-x-1/2 pointer-events-none" />

        {stages.map((stage) => {
          const isCurrent =
            stage.status === 'running' ||
            (!!currentStageName && stage.stage_name === currentStageName && stage.status !== 'completed')
          const time = formatTime(stage.started_at)
          const duration = formatDuration(stage.execution_time_ms)

          return (
            <li
              key={stage.id}
              ref={isCurrent ? activeRef : null}
              className="relative flex items-center justify-between group"
            >
              {/* Left Timestamp */}
              <span
                className="absolute right-full mr-3 text-right text-xs font-mono text-slate-400 tabular-nums select-none"
                aria-hidden
              >
                {time}
              </span>

              {/* Node Icon on Vertical Line */}
              <span
                className={cn(
                  'absolute left-0 -translate-x-1/2 z-10 flex items-center justify-center w-4 h-4 rounded-full shadow-xs',
                  stage.status === 'completed' && 'bg-emerald-500 text-white',
                  stage.status === 'running' && 'bg-blue-600 text-white animate-spin',
                  stage.status === 'waiting' && 'bg-amber-500 text-white',
                  stage.status === 'failed' && 'bg-rose-500 text-white',
                  stage.status === 'blocked' && 'bg-amber-500 text-white',
                  stage.status === 'skipped' && 'bg-slate-300 text-slate-600',
                  !['completed', 'running', 'waiting', 'failed', 'blocked', 'skipped'].includes(stage.status) &&
                    'bg-slate-200 text-slate-500'
                )}
              >
                {stage.status === 'completed' && <Check className="w-2.5 h-2.5 stroke-[3]" />}
                {stage.status === 'running' && <Loader2 className="w-2.5 h-2.5" />}
                {stage.status === 'waiting' && <Clock className="w-2.5 h-2.5" />}
                {stage.status === 'failed' && <X className="w-2.5 h-2.5 stroke-[3]" />}
                {stage.status === 'blocked' && <AlertCircle className="w-2.5 h-2.5" />}
              </span>

              {/* Stage Content */}
              <div className="ml-5 min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p
                    className={cn(
                      'text-xs font-bold leading-tight',
                      stage.status === 'completed' && 'text-slate-900',
                      stage.status === 'running' && 'text-blue-600',
                      stage.status === 'failed' && 'text-rose-600',
                      stage.status === 'waiting' && 'text-amber-700',
                      stage.status === 'skipped' && 'text-slate-400',
                      !['completed', 'running', 'failed', 'waiting', 'skipped'].includes(stage.status) &&
                        'text-slate-600'
                    )}
                  >
                    {formatStageName(stage.stage_name, stage.status)}
                  </p>
                  {isCurrent && stage.status === 'running' && (
                    <span className="text-[10px] font-semibold text-blue-600 bg-blue-50 border border-blue-200 px-1.5 py-0.2 rounded-full">
                      {stage.stage_name === 'superdocs_approval' ? 'Processing…' : 'Running…'}
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2 mt-0.5">
                  {duration && (
                    <span className="text-[11px] font-medium text-slate-400">
                      {duration}
                    </span>
                  )}
                  {stage.error_message && stage.status !== 'completed' && stage.status !== 'skipped' && (
                    <span className="text-[11px] text-rose-600 truncate max-w-xs">
                      {stage.error_message}
                    </span>
                  )}
                  {stage.decision_reason && (
                    <span className="text-[11px] text-slate-500 truncate max-w-xs">
                      {stage.decision_reason}
                    </span>
                  )}
                </div>
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
