import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { History } from 'lucide-react'

import { lineageApi } from '@/core/api/lineageApi'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { PageHeader } from '@/shared/components/PageHeader'
import { Skeleton } from '@/shared/components/ui/skeleton'

import { ReplayTimeline } from './ReplayTimeline'

function ReplaySkeleton() {
  return (
    <div className="space-y-4" aria-label="Loading execution replay">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="flex gap-3">
          <Skeleton className="h-6 w-6 shrink-0 rounded-full" />
          <Skeleton className="h-24 flex-1 rounded-lg" />
        </div>
      ))}
    </div>
  )
}

export function ReplayPage() {
  const navigate = useNavigate()
  const { workspaceId, runId } = useParams<{ workspaceId: string; runId: string }>()

  const replayQuery = useQuery({
    queryKey: ['replay', runId],
    queryFn: () => lineageApi.replayRunExecution(runId!),
    enabled: !!runId,
  })

  const isEmpty =
    replayQuery.isSuccess &&
    replayQuery.data.stages.length === 0 &&
    replayQuery.data.knowledge_reused.length === 0 &&
    replayQuery.data.review_decisions.length === 0

  return (
    <div className="space-y-6">
      <div className="text-sm text-muted-foreground">
        {workspaceId && runId ? (
          <Link
            to={`/workspace/${workspaceId}/runs/${runId}`}
            className="hover:text-foreground hover:underline"
          >
            ← Back to run detail
          </Link>
        ) : (
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="hover:text-foreground hover:underline"
          >
            ← Back
          </button>
        )}
      </div>

      <PageHeader
        title="Execution Replay"
        description="Step-by-step view of how this workflow run executed."
      />

      {replayQuery.isLoading && <ReplaySkeleton />}

      {replayQuery.isError && (
        <ErrorState
          title="Failed to load execution replay"
          description="We could not load the replay timeline for this run. Please try again."
          error={replayQuery.error}
          onRetry={() => void replayQuery.refetch()}
        />
      )}

      {isEmpty && (
        <EmptyState
          icon={History}
          title="No replay data"
          description="There is no execution history available for this workflow run."
          action={
            workspaceId && runId ? (
              <Link
                to={`/workspace/${workspaceId}/runs/${runId}`}
                className="text-sm text-primary hover:underline"
              >
                Back to run detail
              </Link>
            ) : undefined
          }
        />
      )}

      {replayQuery.isSuccess && !isEmpty && <ReplayTimeline timeline={replayQuery.data} />}
    </div>
  )
}
