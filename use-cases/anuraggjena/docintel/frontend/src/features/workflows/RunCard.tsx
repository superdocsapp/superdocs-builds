import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  GitBranch,
  FileText,
  Clock,
  ExternalLink,
  RotateCcw,
  AlertTriangle,
  Play,
  Layers,
  Loader2,
} from 'lucide-react'

import type { WorkflowRun } from '@/core/api/types'
import { runsApi } from '@/core/api/workflowApi'
import { formatStageName, formatWorkflowSlug } from '@/core/labels'
import { formatRelativeTime } from '@/shared/utils/formatDate'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { cn } from '@/lib/utils'

import { getRunActions, type RunAction } from './runActions'
import { ExportDropdown } from '@/features/exports'

export interface RunCardProps {
  run: WorkflowRun
  workspaceId: string
  documentLabel: string
  onKill?: (runId: string) => void
  className?: string
}

export function RunCard({ run, workspaceId, documentLabel, onKill, className }: RunCardProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const actions = getRunActions(run)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const resumeMutation = useMutation({
    mutationFn: () => runsApi.resume(workspaceId, run.id),
    onSuccess: () => {
      setErrorMessage(null)
      queryClient.invalidateQueries({ queryKey: ['runs', workspaceId] })
      queryClient.invalidateQueries({ queryKey: ['run', workspaceId, run.id] })
    },
    onError: (err) => {
      console.error('Resume failed:', err)
      setErrorMessage('Unable to resume this workflow. Please try again.')
    },
  })

  const replayMutation = useMutation({
    mutationFn: () => runsApi.replay(workspaceId, run.id),
    onSuccess: (newRun) => {
      setErrorMessage(null)
      queryClient.invalidateQueries({ queryKey: ['runs', workspaceId] })
      navigate(`/workspace/${workspaceId}/runs/${newRun.id}`)
    },
    onError: (err) => {
      console.error('Replay failed:', err)
      setErrorMessage('Unable to replay this run. Please try again.')
    },
  })

  const workflowLabel = formatWorkflowSlug(run.workflow_slug ?? 'workflow')
  const stageLabel = run.current_stage ? formatStageName(run.current_stage) : null
  const timeLabel = formatRelativeTime(run.started_at ?? run.created_at)


  const handleAction = (action: RunAction) => {
    switch (action) {
      case 'view':
        navigate(`/workspace/${workspaceId}/runs/${run.id}`)
        break
      case 'kill':
        onKill?.(run.id)
        break
      case 'resume':
        resumeMutation.mutate()
        break
      case 'openReview':
        if (run.review_id) {
          navigate(`/workspace/${workspaceId}/reviews/${run.review_id}`)
        }
        break
      case 'screenplayReview':
        navigate(`/workspace/${workspaceId}/runs/${run.id}/review`)
        break
      case 'lineage':
        navigate(`/workspace/${workspaceId}/lineage/run/${run.id}`)
        break
      case 'replay':
        replayMutation.mutate()
        break
    }
  }



  const isWaiting = run.status === 'waiting'
  const isRunning = run.status === 'running' || run.status === 'queued'

  return (
    <div
      className={cn(
        'bg-white border rounded-2xl p-5 shadow-xs transition-all duration-150 flex flex-col md:flex-row md:items-center justify-between gap-4 group',
        isWaiting
          ? 'border-amber-300 ring-1 ring-amber-300/30'
          : isRunning
            ? 'border-blue-300 ring-1 ring-blue-300/30'
            : 'border-slate-200/90 hover:border-slate-300',
        className
      )}
    >
      {/* Left / Info Section */}
      <div className="flex items-start gap-3.5 min-w-0 flex-1">
        <div
          className={cn(
            'w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border mt-0.5',
            isWaiting
              ? 'bg-amber-50 text-amber-600 border-amber-200'
              : isRunning
                ? 'bg-blue-50 text-blue-600 border-blue-200'
                : 'bg-slate-50 text-slate-600 border-slate-200/80'
          )}
        >
          <GitBranch className="w-5 h-5 stroke-[2]" />
        </div>

        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/workspace/${workspaceId}/runs/${run.id}`}
              className="text-sm font-bold text-slate-900 group-hover:text-blue-600 transition-colors truncate"
            >
              {workflowLabel}
            </Link>
            <StatusBadge status={run.status} type="run" />
            {isWaiting && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-semibold bg-amber-100 text-amber-800 rounded-md">
                <AlertTriangle className="w-3 h-3" />
                Action required
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5 text-xs text-slate-500 font-medium">
            <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            <span className="truncate">{documentLabel}</span>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400 pt-0.5">
            {stageLabel && (
              <span className="flex items-center gap-1 font-medium text-slate-600">
                <Layers className="w-3 h-3 text-slate-400" />
                Stage: {stageLabel}
              </span>
            )}
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3 text-slate-400" />
              {timeLabel}
            </span>
            <span className="font-mono text-[11px] text-slate-400">
              ID: {run.id.slice(0, 8)}…
            </span>
          </div>
        </div>
      </div>

      {/* Right / Actions Section */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 pt-2 md:pt-0 border-t md:border-t-0 border-slate-100">
        {actions.includes('openReview') && (
          <button
            type="button"
            onClick={() => handleAction('openReview')}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-amber-500 hover:bg-amber-600 active:bg-amber-700 text-white text-xs font-semibold rounded-lg shadow-xs transition-colors cursor-pointer"
          >
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>Open Review</span>
          </button>
        )}

        {actions.includes('screenplayReview') && (
          <button
            type="button"
            onClick={() => handleAction('screenplayReview')}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-amber-500 hover:bg-amber-600 active:bg-amber-700 text-white text-xs font-semibold rounded-lg shadow-xs transition-colors cursor-pointer"
          >
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>Review</span>
          </button>
        )}

        {actions.includes('resume') && (
          <button
            type="button"
            onClick={() => handleAction('resume')}
            disabled={resumeMutation.isPending}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs font-semibold rounded-lg shadow-xs transition-colors cursor-pointer disabled:opacity-50"
          >
            <Play className="w-3.5 h-3.5" />
            <span>{resumeMutation.isPending ? 'Resuming…' : 'Resume Run'}</span>
          </button>
        )}

        {actions.includes('export') && (
          <ExportDropdown
            workspaceId={workspaceId}
            runId={run.id}
            reviewId={run.review_id}
            workflowSlug={run.workflow_slug}
            variant="emerald"
            size="sm"
          />
        )}


        {actions.includes('replay') && (
          <button
            type="button"
            onClick={() => handleAction('replay')}
            disabled={replayMutation.isPending}
            className="inline-flex items-center gap-1.5 px-3 py-2 border border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-lg transition-colors cursor-pointer disabled:opacity-50"
          >
            {replayMutation.isPending ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Replaying…</span>
              </>
            ) : (
              <>
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Replay Run</span>
              </>
            )}
          </button>
        )}

        {actions.includes('kill') && (
          <button
            type="button"
            onClick={() => handleAction('kill')}
            className="inline-flex items-center px-3 py-2 border border-red-200 hover:bg-red-50 text-red-600 text-xs font-semibold rounded-lg transition-colors cursor-pointer"
          >
            Kill
          </button>
        )}

        <Link
          to={`/workspace/${workspaceId}/runs/${run.id}`}
          className="inline-flex items-center gap-1 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-semibold rounded-lg transition-colors"
        >
          <span>View run</span>
          <ExternalLink className="w-3 h-3 opacity-70" />
        </Link>
      </div>

      {errorMessage && (
        <div className="w-full text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg p-2 flex items-center justify-between">
          <span>{errorMessage}</span>
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            className="text-red-500 hover:text-red-700 font-bold ml-2"
          >
            ×
          </button>
        </div>
      )}
    </div>
  )
}

