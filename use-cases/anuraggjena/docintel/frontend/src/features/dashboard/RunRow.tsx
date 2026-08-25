import { Link } from 'react-router-dom'

import type { WorkflowRun } from '@/core/api/types'
import { formatStageName, formatWorkflowSlug } from '@/core/labels'
import { formatRelativeTime } from '@/shared/utils/formatDate'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { cn } from '@/lib/utils'

export interface RunRowProps {
  run: WorkflowRun
  workspaceId: string
  className?: string
}

export function RunRow({ run, workspaceId, className }: RunRowProps) {
  const workflowLabel = formatWorkflowSlug(run.workflow_slug ?? 'workflow')
  const stageLabel = run.current_stage ? formatStageName(run.current_stage) : null
  const timeLabel = formatRelativeTime(run.started_at ?? run.created_at)

  return (
    <Link
      to={`/workspace/${workspaceId}/runs/${run.id}`}
      className={cn(
        'flex items-center justify-between gap-3 rounded-md px-2 py-2.5 transition-colors hover:bg-muted/50',
        className
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{workflowLabel}</p>
        {stageLabel && (
          <p className="truncate text-xs text-muted-foreground">{stageLabel}</p>
        )}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <StatusBadge status={run.status} type="run" />
        <span className="text-xs text-muted-foreground">{timeLabel}</span>
      </div>
    </Link>
  )
}
