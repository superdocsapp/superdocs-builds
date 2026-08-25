import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Play, Search, X, GitBranch, Filter } from 'lucide-react'

import { workspaceApi } from '@/core/api/client'
import { documentApi } from '@/core/api/documentApi'
import type { WorkflowRun } from '@/core/api/types'
import { runsApi } from '@/core/api/workflowApi'
import { useAuth } from '@/core/auth/AuthContext'
import { formatWorkflowSlug } from '@/core/labels'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { ErrorState } from '@/shared/components/ErrorState'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { cn } from '@/lib/utils'

import { RunCard } from './RunCard'
import { StartWorkflowDialog } from './StartWorkflowDialog'

type FilterTab =
  | 'all'
  | 'running'
  | 'waiting'
  | 'completed'
  | 'failed'
  | 'blocked'
  | 'cancelled'

const FILTER_TABS: Array<{ id: FilterTab; label: string }> = [
  { id: 'all', label: 'All runs' },
  { id: 'running', label: 'Running' },
  { id: 'waiting', label: 'Waiting for review' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
  { id: 'blocked', label: 'Blocked' },
  { id: 'cancelled', label: 'Cancelled' },
]

type RunWithDocument = WorkflowRun & { document_id?: string | null }

function matchesFilter(run: WorkflowRun, tab: FilterTab): boolean {
  switch (tab) {
    case 'all':
      return true
    case 'running':
      return run.status === 'queued' || run.status === 'running'
    case 'waiting':
      return run.status === 'waiting'
    case 'completed':
      return run.status === 'completed'
    case 'failed':
      return run.status === 'failed'
    case 'blocked':
      return run.status === 'blocked'
    case 'cancelled':
      return run.status === 'cancelled'
    default:
      return true
  }
}

function sortByRecent(runs: WorkflowRun[]): WorkflowRun[] {
  return [...runs].sort((a, b) => {
    const aTime = new Date(a.started_at ?? a.created_at).getTime()
    const bTime = new Date(b.started_at ?? b.created_at).getTime()
    return bTime - aTime
  })
}

function getDocumentLabel(
  run: RunWithDocument,
  documentsById: Map<string, { filename: string }>,
  workspaceName?: string | null
): string {
  if (run.document_id) {
    const document = documentsById.get(run.document_id)
    if (document) return document.filename
  }
  return workspaceName ?? 'Workflow run'
}

export function RunsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const { accessToken } = useAuth()
  const queryClient = useQueryClient()

  const [filterTab, setFilterTab] = useState<FilterTab>('all')
  const [search, setSearch] = useState('')
  const [startDialogOpen, setStartDialogOpen] = useState(false)
  const [killTargetId, setKillTargetId] = useState<string | null>(null)

  const workspaceQuery = useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => workspaceApi.get(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const documentsQuery = useQuery({
    queryKey: ['documents', workspaceId],
    queryFn: () => documentApi.list(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const runsQuery = useQuery({
    queryKey: ['runs', workspaceId],
    queryFn: () => runsApi.list(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
    refetchInterval: (query) => {
      const runs = query.state.data ?? []
      const hasActive = runs.some((run) =>
        ['queued', 'running', 'waiting'].includes(run.status)
      )
      return hasActive ? 5000 : false
    },
  })

  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const cancelMutation = useMutation({
    mutationFn: (runId: string) => runsApi.cancel(workspaceId!, runId),
    onSuccess: () => {
      setErrorMessage(null)
      queryClient.invalidateQueries({ queryKey: ['runs', workspaceId] })
      setKillTargetId(null)
    },
    onError: (err) => {
      console.error('Cancel failed:', err)
      setErrorMessage('Unable to stop this workflow. Please try again.')
    },
  })

  const documentsById = useMemo(() => {
    const map = new Map<string, { filename: string }>()
    for (const document of documentsQuery.data ?? []) {
      map.set(document.id, { filename: document.filename })
    }
    return map
  }, [documentsQuery.data])

  const allRuns = runsQuery.data ?? []

  // Counts for each tab
  const counts = useMemo(() => {
    const map: Record<FilterTab, number> = {
      all: allRuns.length,
      running: allRuns.filter((r) => r.status === 'running' || r.status === 'queued').length,
      waiting: allRuns.filter((r) => r.status === 'waiting').length,
      completed: allRuns.filter((r) => r.status === 'completed').length,
      failed: allRuns.filter((r) => r.status === 'failed').length,
      blocked: allRuns.filter((r) => r.status === 'blocked').length,
      cancelled: allRuns.filter((r) => r.status === 'cancelled').length,
    }
    return map
  }, [allRuns])

  const filteredRuns = useMemo(() => {
    const workspaceName = workspaceQuery.data?.name

    let result = allRuns.filter((run) => matchesFilter(run, filterTab))

    if (search.trim()) {
      const query = search.trim().toLowerCase()
      result = result.filter((run) => {
        const workflowLabel = formatWorkflowSlug(run.workflow_slug ?? 'workflow').toLowerCase()
        const documentLabel = getDocumentLabel(run, documentsById, workspaceName).toLowerCase()
        return workflowLabel.includes(query) || documentLabel.includes(query)
      })
    }

    return sortByRecent(result)
  }, [allRuns, filterTab, search, documentsById, workspaceQuery.data?.name])

  const killTarget = allRuns.find((run) => run.id === killTargetId)

  const handleConfirmKill = () => {
    if (killTargetId) {
      cancelMutation.mutate(killTargetId)
    }
  }

  if (!workspaceId) {
    return null
  }

  const isLoading = workspaceQuery.isLoading || documentsQuery.isLoading || runsQuery.isLoading
  const error = workspaceQuery.error ?? documentsQuery.error ?? runsQuery.error

  const refetchAll = () => {
    workspaceQuery.refetch()
    documentsQuery.refetch()
    runsQuery.refetch()
  }

  return (
    <div className="space-y-6">
      {/* 1. Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
            Workflow Runs
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Monitor execution history, review checkpoints, and inspect pipeline stages.
          </p>
        </div>

        <div>
          <button
            type="button"
            onClick={() => setStartDialogOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs sm:text-sm font-semibold rounded-lg shadow-sm transition-all duration-150 cursor-pointer"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>Start workflow</span>
          </button>
        </div>
      </div>

      {/* Error Alert */}
      {errorMessage && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 text-xs rounded-xl p-3 flex items-center justify-between">
          <span>{errorMessage}</span>
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            className="text-rose-600 hover:text-rose-900 font-bold px-2"
          >
            ×
          </button>
        </div>
      )}

      {/* 2. Filter Pills & Search Toolbar */}
      <div className="space-y-3">
        {/* Filter Pills */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 no-scrollbar">
          {FILTER_TABS.map((tab) => {
            const isActive = filterTab === tab.id
            const count = counts[tab.id]
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setFilterTab(tab.id)}
                className={cn(
                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all duration-150 cursor-pointer',
                  isActive
                    ? 'bg-slate-900 text-white shadow-xs'
                    : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                )}
              >
                <span>{tab.label}</span>
                {count > 0 && (
                  <span
                    className={cn(
                      'px-1.5 py-0.2 rounded-full text-[10px] font-bold',
                      isActive ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-600'
                    )}
                  >
                    {count}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {/* Search Input */}
        <div className="relative">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
          <input
            type="text"
            placeholder="Search by workflow name, document, or ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full h-10 pl-9 pr-8 bg-white border border-slate-200 rounded-xl text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-600 focus:border-blue-600 shadow-xs"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-1 cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* 3. Workflow Run Cards List */}
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs flex items-center justify-between gap-4"
            >
              <div className="flex items-center gap-3.5 min-w-0 flex-1">
                <Skeleton className="w-10 h-10 rounded-xl" />
                <div className="space-y-2 min-w-0 flex-1">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-3 w-64" />
                </div>
              </div>
              <Skeleton className="h-9 w-24 rounded-lg" />
            </div>
          ))}
        </div>
      ) : error ? (
        <ErrorState
          title="Could not load workflow runs"
          description="Something went wrong while fetching workflow runs for this workspace."
          onRetry={refetchAll}
          error={error}
        />
      ) : allRuns.length === 0 ? (
        <div className="bg-white border border-slate-200/90 rounded-2xl p-12 text-center shadow-sm">
          <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 border border-blue-100 flex items-center justify-center mx-auto mb-3">
            <GitBranch className="w-6 h-6 stroke-[1.75]" />
          </div>
          <h3 className="text-base font-bold text-slate-900 tracking-tight">
            No workflow runs yet
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto mb-5">
            Start a workflow run to process your uploaded documents and generate classifications.
          </p>
          <button
            type="button"
            onClick={() => setStartDialogOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs font-semibold rounded-lg shadow-sm transition-all cursor-pointer"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>Start your first workflow</span>
          </button>
        </div>
      ) : filteredRuns.length === 0 ? (
        <div className="bg-white border border-slate-200/90 rounded-2xl p-10 text-center shadow-sm">
          <div className="w-10 h-10 rounded-xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-2.5">
            <Filter className="w-5 h-5" />
          </div>
          <h3 className="text-sm font-bold text-slate-900">No matching runs</h3>
          <p className="text-xs text-slate-500 mt-0.5 mb-4">
            No workflow runs match your active filter and search criteria.
          </p>
          <button
            type="button"
            onClick={() => {
              setSearch('')
              setFilterTab('all')
            }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors cursor-pointer"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div className="space-y-3.5">
          {filteredRuns.map((run) => (
            <RunCard
              key={run.id}
              run={run}
              workspaceId={workspaceId}
              documentLabel={getDocumentLabel(run, documentsById, workspaceQuery.data?.name)}
              onKill={setKillTargetId}
            />
          ))}
        </div>
      )}

      {/* Start Workflow Dialog */}
      <StartWorkflowDialog
        open={startDialogOpen}
        onOpenChange={setStartDialogOpen}
        workspaceId={workspaceId}
        documents={documentsQuery.data ?? []}
        workspaceWorkflowType={workspaceQuery.data?.workflow_type}
      />

      {/* Kill Confirmation Dialog */}
      <ConfirmDialog
        open={killTargetId !== null}
        title="Kill workflow run"
        description={
          killTarget
            ? `Stop the ${formatWorkflowSlug(killTarget.workflow_slug ?? 'workflow')} run? This cannot be undone.`
            : 'Stop this workflow run? This cannot be undone.'
        }
        confirmLabel="Kill run"
        destructive
        onConfirm={handleConfirmKill}
        onCancel={() => setKillTargetId(null)}
      />
    </div>
  )
}

