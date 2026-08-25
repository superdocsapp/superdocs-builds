import { useState } from 'react'
import {
  AlertCircle,
  Ban,
  CheckCircle2,
  ChevronDown,
  Circle,
  Clock,
  Loader2,
  SkipForward,
} from 'lucide-react'

import {
  ReplayStage,
  ReplayTimeline as ReplayTimelineData,
} from '@/core/api/lineageApi'
import { formatStageName } from '@/core/labels'
import { cn } from '@/lib/utils'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { TechnicalDetails } from '@/shared/components/TechnicalDetails'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'
import { formatRelativeTime } from '@/shared/utils/formatDate'

interface ReplayTimelineProps {
  timeline: ReplayTimelineData
  claimId?: string
}

function formatDuration(ms?: number): string | null {
  if (ms == null) return null
  if (ms < 1000) return `${ms}ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = Math.round(seconds % 60)
  return `${minutes}m ${remainingSeconds}s`
}

function formatKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return JSON.stringify(value, null, 2)
}

function KeyValueGrid({
  data,
  title,
}: {
  data: Record<string, unknown>
  title: string
}) {
  const entries = Object.entries(data)
  if (entries.length === 0) return null

  return (
    <div>
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      <dl className="space-y-2 rounded-md border border-border bg-muted/20 p-3">
        {entries.map(([key, value]) => (
          <div key={key} className="grid gap-1 text-sm sm:grid-cols-[minmax(0,1fr)_2fr] sm:gap-3">
            <dt className="font-medium text-muted-foreground">{formatKey(key)}</dt>
            <dd className="whitespace-pre-wrap break-words">{formatValue(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function StageStatusIcon({ status }: { status: string }) {
  const className = 'h-4 w-4 shrink-0'

  switch (status) {
    case 'completed':
      return <CheckCircle2 className={cn(className, 'text-green-600')} aria-hidden />
    case 'failed':
      return <AlertCircle className={cn(className, 'text-red-600')} aria-hidden />
    case 'running':
      return (
        <Loader2
          className={cn(className, 'text-blue-600 motion-safe:animate-spin')}
          aria-hidden
        />
      )
    case 'skipped':
      return <SkipForward className={cn(className, 'text-slate-400')} aria-hidden />
    case 'blocked':
      return <Ban className={cn(className, 'text-orange-600')} aria-hidden />
    case 'queued':
      return <Clock className={cn(className, 'text-slate-400')} aria-hidden />
    default:
      return <Circle className={cn(className, 'text-slate-400')} aria-hidden />
  }
}

function ReplayStageCard({
  stage,
  index,
  claimId,
}: {
  stage: ReplayStage
  index: number
  claimId?: string
}) {
  const [expanded, setExpanded] = useState(false)
  const duration = formatDuration(stage.execution_time_ms)
  const relativeTime = stage.started_at ? formatRelativeTime(stage.started_at) : null
  const isContributed = !!claimId && stage.contributed_to_claim
  const hasDetails =
    (stage.inputs && Object.keys(stage.inputs).length > 0) ||
    (stage.outputs && Object.keys(stage.outputs).length > 0) ||
    !!stage.started_at ||
    !!stage.completed_at
  const stageJson = JSON.stringify(stage, null, 2)

  return (
    <li className="relative pl-10">
      <div className="absolute left-3 top-5 z-10 flex h-6 w-6 items-center justify-center rounded-full border-2 border-background bg-card">
        <StageStatusIcon status={stage.status} />
      </div>

      <Card
        className={cn(
          'transition-colors',
          isContributed && 'border-blue-300 bg-blue-50/40'
        )}
      >
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <CardTitle className="text-base">
                  {formatStageName(stage.stage_name)}
                </CardTitle>
                <StatusBadge status={stage.status} type="stage" />
                {duration && (
                  <span className="text-xs text-muted-foreground">{duration}</span>
                )}
                {relativeTime && (
                  <span className="text-xs text-muted-foreground">{relativeTime}</span>
                )}
              </div>

              {isContributed && (
                <p className="text-xs font-medium text-blue-700">
                  Contributed to selected claim
                </p>
              )}
            </div>

            {hasDetails && (
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                aria-expanded={expanded}
                aria-controls={`replay-stage-${index}`}
              >
                <ChevronDown
                  className={cn('h-4 w-4 transition-transform', expanded && 'rotate-180')}
                />
                {expanded ? 'Collapse' : 'Expand'}
              </button>
            )}
          </div>
        </CardHeader>

        {expanded && hasDetails && (
          <CardContent id={`replay-stage-${index}`} className="space-y-4 border-t pt-4">
            {(stage.started_at || stage.completed_at) && (
              <div className="grid gap-3 sm:grid-cols-2">
                {stage.started_at && (
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Started
                    </p>
                    <p className="mt-1 text-sm">{new Date(stage.started_at).toLocaleString()}</p>
                  </div>
                )}
                {stage.completed_at && (
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Completed
                    </p>
                    <p className="mt-1 text-sm">
                      {new Date(stage.completed_at).toLocaleString()}
                    </p>
                  </div>
                )}
              </div>
            )}

            {stage.inputs && Object.keys(stage.inputs).length > 0 && (
              <KeyValueGrid data={stage.inputs} title="Inputs" />
            )}

            {stage.outputs && Object.keys(stage.outputs).length > 0 && (
              <KeyValueGrid data={stage.outputs} title="Outputs" />
            )}
          </CardContent>
        )}

        <CardContent className={expanded && hasDetails ? 'border-t pt-4' : 'pt-0'}>
          <TechnicalDetails copyText={stageJson} label="Technical details">
            {stageJson}
          </TechnicalDetails>
        </CardContent>
      </Card>
    </li>
  )
}

function KnowledgeReusedCard({ entry }: { entry: Record<string, unknown> }) {
  const contentPreview = typeof entry.content_preview === 'string' ? entry.content_preview : null
  const stageName = typeof entry.stage_name === 'string' ? entry.stage_name : null
  const entryType = typeof entry.entry_type === 'string' ? entry.entry_type : null

  return (
    <Card className="border-purple-200 bg-purple-50/40">
      <CardContent className="space-y-2 p-4">
        {contentPreview && (
          <p className="text-sm text-foreground">{contentPreview}</p>
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {stageName && (
            <span className="rounded-full bg-background px-2 py-0.5">
              {formatStageName(stageName)}
            </span>
          )}
          {entryType && (
            <span className="rounded-full bg-background px-2 py-0.5">
              {formatKey(entryType)}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function ReviewDecisionCard({ decision }: { decision: Record<string, unknown> }) {
  const action =
    (typeof decision.action === 'string' && decision.action) ||
    (typeof decision.status === 'string' && decision.status) ||
    'unknown'
  const contentPreview =
    typeof decision.content_preview === 'string' ? decision.content_preview : null
  const notes = typeof decision.notes === 'string' ? decision.notes : null
  const sourceStage =
    typeof decision.source_stage === 'string' ? decision.source_stage : null
  const statusType = action === 'approved' || action === 'rejected' ? 'claim' : 'review'

  return (
    <Card
      className={cn(
        action === 'approved' && 'border-green-200 bg-green-50/40',
        action === 'rejected' && 'border-red-200 bg-red-50/40',
        action !== 'approved' && action !== 'rejected' && 'border-amber-200 bg-amber-50/40'
      )}
    >
      <CardContent className="space-y-2 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={action} type={statusType} />
          {sourceStage && (
            <span className="text-xs text-muted-foreground">
              from {formatStageName(sourceStage)}
            </span>
          )}
        </div>
        {contentPreview && <p className="text-sm text-foreground">{contentPreview}</p>}
        {notes && <p className="text-sm text-muted-foreground">{notes}</p>}
      </CardContent>
    </Card>
  )
}

export function ReplayTimeline({ timeline, claimId }: ReplayTimelineProps) {
  const timelineJson = JSON.stringify(timeline, null, 2)

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {timeline.stages.length} stage{timeline.stages.length === 1 ? '' : 's'}
          {timeline.knowledge_reused.length > 0 &&
            ` · ${timeline.knowledge_reused.length} knowledge reuse${
              timeline.knowledge_reused.length === 1 ? '' : 's'
            }`}
          {timeline.review_decisions.length > 0 &&
            ` · ${timeline.review_decisions.length} review decision${
              timeline.review_decisions.length === 1 ? '' : 's'
            }`}
        </p>
        <TechnicalDetails copyText={timelineJson} label="Run technical details">
          {timelineJson}
        </TechnicalDetails>
      </div>

      {timeline.stages.length > 0 && (
        <section className="space-y-4">
          <h2 className="text-lg font-semibold">Execution stages</h2>
          <div className="relative">
            <div
              className="absolute bottom-0 left-5 top-0 w-px bg-border"
              aria-hidden
            />
            <ol className="space-y-4" aria-label="Execution stages">
              {timeline.stages.map((stage, index) => (
                <ReplayStageCard
                  key={`${stage.stage_name}-${index}`}
                  stage={stage}
                  index={index}
                  claimId={claimId}
                />
              ))}
            </ol>
          </div>
        </section>
      )}

      {timeline.knowledge_reused.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">
            Knowledge reused ({timeline.knowledge_reused.length})
          </h2>
          <div className="space-y-3">
            {timeline.knowledge_reused.map((entry, index) => (
              <KnowledgeReusedCard key={index} entry={entry} />
            ))}
          </div>
        </section>
      )}

      {timeline.review_decisions.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">
            Review decisions ({timeline.review_decisions.length})
          </h2>
          <div className="space-y-3">
            {timeline.review_decisions.map((decision, index) => (
              <ReviewDecisionCard key={index} decision={decision} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
