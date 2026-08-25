import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { GitBranch } from 'lucide-react'

import { lineageApi } from '@/core/api/lineageApi'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { PageHeader } from '@/shared/components/PageHeader'
import { Label } from '@/shared/components/ui/label'

import { LineageFlowGraph } from './LineageFlowGraph'
import { LineageSkeleton } from './LineageSkeleton'

interface LineagePageProps {
  mode: 'run' | 'claim'
}

export function LineagePage({ mode }: LineagePageProps) {
  const navigate = useNavigate()
  const { workspaceId, runId, claimId } = useParams<{
    workspaceId: string
    runId?: string
    claimId?: string
  }>()
  const [depth, setDepth] = useState(3)

  const entityId = mode === 'run' ? runId : claimId

  const lineageQuery = useQuery({
    queryKey: ['lineage', mode, entityId, depth],
    queryFn: () => {
      if (mode === 'run') {
        return lineageApi.getRunLineage(runId!)
      }
      return lineageApi.getClaimLineage(claimId!, depth)
    },
    enabled: !!entityId,
  })

  const title = mode === 'run' ? 'Run Lineage' : 'Claim Lineage'
  const description =
    mode === 'run'
      ? 'See how this classification was built from your documents, evidence, analysis, and approved findings.'
      : 'Trace how this claim was derived from source documents and prior knowledge.'

  return (
    <div className="space-y-6">
      <div className="text-sm text-muted-foreground">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="hover:text-foreground hover:underline"
        >
          ← Back
        </button>
      </div>

      <PageHeader
        title={title}
        description={description}
        actions={
          mode === 'claim' ? (
            <div className="flex w-full min-w-[200px] flex-col gap-2 sm:w-auto">
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="lineage-depth" className="text-sm text-muted-foreground">
                  Depth
                </Label>
                <span className="text-sm font-medium">{depth}</span>
              </div>
              <input
                id="lineage-depth"
                type="range"
                min={1}
                max={5}
                step={1}
                value={depth}
                onChange={(event) => setDepth(Number(event.target.value))}
                className="w-full accent-primary"
                aria-label="Lineage traversal depth"
              />
            </div>
          ) : undefined
        }
      />

      {lineageQuery.isLoading && <LineageSkeleton />}

      {lineageQuery.isError && (
        <ErrorState
          title="Failed to load lineage"
          description="We could not load the lineage graph. Please try again."
          error={lineageQuery.error}
          onRetry={() => void lineageQuery.refetch()}
        />
      )}

      {lineageQuery.isSuccess && lineageQuery.data.nodes.length === 0 && (
        <EmptyState
          icon={GitBranch}
          title="No lineage data"
          description="There are no nodes in the lineage graph for this selection."
          action={
            workspaceId ? (
              <Link
                to={`/workspace/${workspaceId}/runs`}
                className="text-sm text-primary hover:underline"
              >
                Back to workflow runs
              </Link>
            ) : undefined
          }
        />
      )}

      {lineageQuery.isSuccess && lineageQuery.data.nodes.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {lineageQuery.data.nodes.length} nodes, {lineageQuery.data.edges.length} connections
          </p>
          <LineageFlowGraph graph={lineageQuery.data} />
        </div>
      )}
    </div>
  )
}
