import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Calendar,
  Check,
  Clock,
  Copy,
  FileText,
  GitFork,
  History,
  Loader2,
  Play,
  RotateCcw,
  XCircle,
} from 'lucide-react'

import { workspaceApi } from '@/core/api/client'

import { evidenceApi } from '@/core/api/evidenceApi'
import type { Evidence, WorkflowRun, WorkflowStage } from '@/core/api/types'
import { runsApi } from '@/core/api/workflowApi'
import { reviewApi } from '@/core/api/reviewApi'
import { exportApi } from '@/core/api/exportApi'
import { useAuth } from '@/core/auth/AuthContext'
import { useSetLiveConnection } from '@/core/layout/LiveConnectionContext'
import { formatWorkflowSlug } from '@/core/labels'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { ErrorState } from '@/shared/components/ErrorState'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { formatDate } from '@/shared/utils/formatDate'

import { QualityGateResult } from '../quality-gate/QualityGateResult'
import { HumanApprovalModal } from './HumanApprovalModal'
import { StageTimeline } from './StageTimeline'
import { useRunLiveUpdates } from './useRunLiveUpdates'
import { ScreenplayWorkspacePage } from '@/features/screenplay'
import { ExportDropdown } from '@/features/exports'
import { getRunActions } from './runActions'



const ACTIVE_STREAM_STATUSES = new Set(['queued', 'running', 'waiting'])

function formatTotalDuration(startedAt?: string | null, completedAt?: string | null): string {
  if (!startedAt) return '—'
  const start = new Date(startedAt.endsWith('Z') || startedAt.includes('+') ? startedAt : startedAt + 'Z').getTime()
  const end = completedAt
    ? new Date(completedAt.endsWith('Z') || completedAt.includes('+') ? completedAt : completedAt + 'Z').getTime()
    : Date.now()

  const diffMs = Math.max(0, end - start)
  const totalSeconds = Math.floor(diffMs / 1000)
  if (totalSeconds < 60) return `${totalSeconds}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}m ${seconds}s`
}

function RunDetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-8 w-96 max-w-full" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <Skeleton className="lg:col-span-5 h-[500px] rounded-2xl" />
        <div className="lg:col-span-7 space-y-6">
          <Skeleton className="h-44 rounded-2xl" />
          <Skeleton className="h-56 rounded-2xl" />
          <Skeleton className="h-44 rounded-2xl" />
        </div>
      </div>
    </div>
  )
}

export function RunDetailPage() {
  const { workspaceId, runId } = useParams<{ workspaceId: string; runId: string }>()
  const navigate = useNavigate()
  const { accessToken } = useAuth()

  const [killConfirmOpen, setKillConfirmOpen] = useState(false)
  const [approvalModalOpen, setApprovalModalOpen] = useState(false)
  const [copiedId, setCopiedId] = useState(false)
  const isPollingRef = useRef(false)
  const hasAutoOpenedReviewRef = useRef(false)
  const hasAutoDownloadedRef = useRef<Set<string>>(new Set())
  const initialRunStatusRef = useRef<Map<string, string>>(new Map())

  // 1. Workspace query
  const workspaceQuery = useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => workspaceApi.get(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  // 2. Workflow run query
  const runQuery = useQuery<WorkflowRun>({
    queryKey: ['run', workspaceId, runId],
    queryFn: () => runsApi.get(workspaceId!, runId!),
    enabled: !!workspaceId && !!runId && !!accessToken,
    refetchInterval: (query) => {
      const currentRun = query.state.data
      if (!currentRun) return 2000
      return ACTIVE_STREAM_STATUSES.has(currentRun.status) ? 2000 : false
    },
  })

  // 3. Live WebSocket / polling updates
  const { liveState, invalidateRunQueries, isPolling } = useRunLiveUpdates(
    workspaceId,
    runId,
    runQuery.data?.status
  )
  isPollingRef.current = isPolling
  useSetLiveConnection(liveState)

  // 4. Stages query
  const stagesQuery = useQuery<WorkflowStage[]>({
    queryKey: ['run-stages', runId],
    queryFn: () => runsApi.getStages(workspaceId!, runId!),
    enabled: !!workspaceId && !!runId && !!accessToken,
    refetchInterval: () => {
      const currentRun = runQuery.data
      if (!currentRun) return 2000
      return ACTIVE_STREAM_STATUSES.has(currentRun.status) ? 2000 : false
    },
  })

  // 5. Claims query for HITL approval
  const claimsQuery = useQuery({
    queryKey: ['run-claims', runId],
    queryFn: () => runsApi.getClaims(workspaceId!, runId!),
    enabled: !!workspaceId && !!runId && !!accessToken,
    refetchInterval: () => {
      return runQuery.data?.status === 'waiting' ? 3000 : false
    },
  })

  // 6. Evidence query
  const evidenceQuery = useQuery<Evidence[]>({
    queryKey: ['evidence', runId],
    queryFn: () => evidenceApi.listForRun(runId!),
    enabled: !!runId && !!accessToken,
    refetchInterval: () => {
      const currentRun = runQuery.data
      if (!currentRun) return 3000
      return ACTIVE_STREAM_STATUSES.has(currentRun.status) ? 3000 : false
    },
  })

  const workspace = workspaceQuery.data
  const run = runQuery.data
  const stages = stagesQuery.data ?? []
  const claims = claimsQuery.data ?? []
  const evidence = evidenceQuery.data ?? []

  // Track initial run status on first load to prevent auto-download when merely opening an already-completed run
  useEffect(() => {
    if (!runId || !run?.status) return
    if (!initialRunStatusRef.current.has(runId)) {
      initialRunStatusRef.current.set(runId, run.status)
      if (run.status === 'completed') {
        // Run was already completed when this session/page mounted — do not auto-download
        hasAutoDownloadedRef.current.add(runId)
      }
    }
  }, [runId, run?.status])

  // Invalidate and refetch dependent queries on run status transition
  const prevStatusRef = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (run?.status && prevStatusRef.current && prevStatusRef.current !== run.status) {
      invalidateRunQueries()
    }
    prevStatusRef.current = run?.status
  }, [run?.status, invalidateRunQueries])

  // Auto-download generated DOCX when run completes
  useEffect(() => {
    if (run?.status !== 'completed' || !workspaceId || !runId) return
    if (hasAutoDownloadedRef.current.has(runId)) return

    let isMounted = true
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const tryAutoDownload = async (attempt = 0) => {
      if (!isMounted || hasAutoDownloadedRef.current.has(runId)) return

      try {
        const exportsList = await exportApi.listByWorkspace(workspaceId)
        if (!isMounted) return

        // Look for DOCX export strictly associated with this run ID
        const runExport = exportsList.find(
          (exp) => exp.workflow_run_id === runId && exp.format.toLowerCase() === 'docx'
        )

        if (runExport) {
          hasAutoDownloadedRef.current.add(runId)
          await exportApi.download(
            runExport.id,
            runExport.filename || `report_${runId.slice(0, 8)}.docx`
          )
          return
        }

        // If no export record is found yet after initial retries, trigger explicit exportRun
        if (attempt >= 3 && isMounted) {
          try {
            const result = await exportApi.exportRun(
              workspaceId,
              runId,
              run.workflow_slug ?? undefined,
              'docx'
            )
            if (result && isMounted) {
              hasAutoDownloadedRef.current.add(runId)
              await exportApi.download(result.export_id, result.filename)
              return
            }
          } catch (triggerErr) {
            console.warn('Auto-download exportRun fallback failed:', triggerErr)
          }
        }

        // Retry briefly (up to 5 attempts, every 1.5s) in case export record creation is finalizing
        if (attempt < 5 && isMounted) {
          retryTimer = setTimeout(() => {
            void tryAutoDownload(attempt + 1)
          }, 1500)
        }
      } catch (err) {
        console.warn('Auto-download lookup failed:', err)
        if (attempt < 5 && isMounted) {
          retryTimer = setTimeout(() => {
            void tryAutoDownload(attempt + 1)
          }, 1500)
        }
      }
    }

    void tryAutoDownload()

    return () => {
      isMounted = false
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [run?.status, runId, workspaceId, run?.workflow_slug])

  // Auto-open approval modal once when waiting for human review
  useEffect(() => {
    if (run?.status === 'waiting' && claims.length > 0 && !hasAutoOpenedReviewRef.current) {
      hasAutoOpenedReviewRef.current = true
      setApprovalModalOpen(true)
    }
  }, [run?.status, claims.length])

  const [actionError, setActionError] = useState<string | null>(null)

  // Resume mutation
  const resumeMutation = useMutation({
    mutationFn: () => runsApi.resume(workspaceId!, runId!),
    onSuccess: () => {
      setActionError(null)
      invalidateRunQueries()
    },
    onError: (err) => {
      console.error('Resume failed:', err)
      setActionError('Unable to resume this workflow. Please try again.')
    },
  })

  // Cancel / Kill mutation
  const cancelMutation = useMutation({
    mutationFn: () => runsApi.cancel(workspaceId!, runId!),
    onSuccess: () => {
      setActionError(null)
      setKillConfirmOpen(false)
      invalidateRunQueries()
    },
    onError: (err) => {
      console.error('Kill failed:', err)
      setActionError('Unable to stop this workflow. Please try again.')
    },
  })

  // Replay mutation (creates new run from this run)
  const replayMutation = useMutation({
    mutationFn: () => runsApi.replay(workspaceId!, runId!),
    onSuccess: (newRun) => {
      setActionError(null)
      invalidateRunQueries()
      navigate(`/workspace/${workspaceId}/runs/${newRun.id}`)
    },
    onError: (err) => {
      console.error('Replay failed:', err)
      setActionError('Unable to replay this run. Please try again.')
    },
  })

  // Approve claim mutation
  const approveClaimMutation = useMutation({
    mutationFn: (claimId: string) => reviewApi.approveClaim(claimId),
    onSuccess: () => {
      void claimsQuery.refetch()
      invalidateRunQueries()
      // Resume run automatically after approving
      resumeMutation.mutate()
    },
  })

  // Reject claim mutation
  const rejectClaimMutation = useMutation({
    mutationFn: (claimId: string) => reviewApi.rejectClaim(claimId),
    onSuccess: () => {
      void claimsQuery.refetch()
      invalidateRunQueries()
      // Resume run automatically after rejecting
      resumeMutation.mutate()
    },
  })

  // Approve all claims mutation
  const approveAllClaimsMutation = useMutation({
    mutationFn: () => runsApi.approveAllClaims(workspaceId!, runId!),
    onSuccess: (data) => {
      setActionError(null)
      setApprovalModalOpen(false)
      void claimsQuery.refetch()
      invalidateRunQueries()
      if (!data.resumed && run?.status === 'waiting') {
        resumeMutation.mutate()
      }
    },
    onError: (err: any) => {
      console.error('Approve all failed:', err)
      const detail = err?.response?.data?.detail || 'Unable to approve all changes. Please try again.'
      setActionError(detail)
    },
  })

  // Copy Run ID
  const handleCopyId = () => {
    if (!runId) return

    navigator.clipboard.writeText(runId)
    setCopiedId(true)
    setTimeout(() => setCopiedId(false), 2000)
  }

  const isLoading = workspaceQuery.isLoading || runQuery.isLoading || stagesQuery.isLoading
  const error = workspaceQuery.error ?? runQuery.error ?? stagesQuery.error

  if (isLoading) {
    return <RunDetailSkeleton />
  }

  if (error || !run) {
    return (
      <ErrorState
        title="Could not load workflow run"
        description="Something went wrong while fetching this run details."
        onRetry={() => {
          void workspaceQuery.refetch()
          void runQuery.refetch()
          void stagesQuery.refetch()
        }}
        error={error}
      />
    )
  }

  if (run.workflow_slug === 'screenplay' || workspace?.workflow_type === 'screenplay') {
    return <ScreenplayWorkspacePage customRunId={run.id} />
  }

  const effectiveSlug = run.workflow_slug || workspace?.workflow_type || 'tariff_classification'
  const workflowLabel = formatWorkflowSlug(effectiveSlug)
  const runCodePrefix = effectiveSlug.toLowerCase().includes('screenplay') ? 'SCR' : 'TRF'
  const formattedRunCode = `${runCodePrefix}-${run.id.slice(0, 8).toUpperCase()}`
  const totalTime = formatTotalDuration(run.started_at, run.completed_at)
  const completedStagesCount = stages.filter((s) => s.status === 'completed').length
  const totalStagesCount = stages.length > 0 ? stages.length : 17
  const actions = getRunActions(run)

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      {/* 1. Header & Navigation */}
      <div className="space-y-3">
        {/* Breadcrumb */}
        <div className="flex items-center gap-1.5 text-xs text-slate-500 font-medium">
          <Link
            to={`/workspace/${workspaceId}/runs`}
            className="hover:text-slate-900 transition-colors"
          >
            Workflow Runs
          </Link>
          <span className="text-slate-400">/</span>
          <span className="text-slate-800 font-mono font-semibold">{formattedRunCode}</span>
        </div>

        {/* Title Row & Actions */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
                {formattedRunCode}
              </h1>
              <StatusBadge status={run.status} type="run" />
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span className="font-medium text-slate-700">{workflowLabel}</span>
              <span>•</span>
              <span className="font-mono">v{run.workflow_version}</span>
              <span>•</span>
              <span className="flex items-center gap-1">
                <Calendar className="w-3.5 h-3.5 text-slate-400" />
                {formatDate(run.created_at)}
              </span>
              <span>•</span>
              <span className="flex items-center gap-1">
                <Clock className="w-3.5 h-3.5 text-slate-400" />
                Total time: {totalTime}
              </span>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={() => navigate(`/workspace/${workspaceId}/lineage/run/${run.id}`)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-xl shadow-xs transition-colors cursor-pointer"
            >
              <GitFork className="w-3.5 h-3.5 text-slate-500" />
              <span>Lineage</span>
            </button>

            <button
              type="button"
              onClick={() => navigate(`/workspace/${workspaceId}/replay/${run.id}`)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-xl shadow-xs transition-colors cursor-pointer"
            >
              <History className="w-3.5 h-3.5 text-slate-500" />
              <span>Timeline</span>
            </button>

            {actions.includes('replay') && (
              <button
                type="button"
                onClick={() => replayMutation.mutate()}
                disabled={replayMutation.isPending}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-xl shadow-xs transition-colors cursor-pointer disabled:opacity-50"
              >
                {replayMutation.isPending ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600" />
                    <span>Replaying…</span>
                  </>
                ) : (
                  <>
                    <RotateCcw className="w-3.5 h-3.5 text-blue-600" />
                    <span>Replay Run</span>
                  </>
                )}
              </button>
            )}

            {actions.includes('kill') && (
              <button
                type="button"
                onClick={() => setKillConfirmOpen(true)}
                disabled={cancelMutation.isPending}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-rose-50 border border-rose-200 hover:bg-rose-100 text-rose-700 text-xs font-semibold rounded-xl shadow-xs transition-colors cursor-pointer disabled:opacity-50"
              >
                {cancelMutation.isPending ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Stopping…</span>
                  </>
                ) : (
                  <>
                    <XCircle className="w-3.5 h-3.5" />
                    <span>Kill Run</span>
                  </>
                )}
              </button>
            )}

            {actions.includes('resume') && (
              <button
                type="button"
                onClick={() => resumeMutation.mutate()}
                disabled={resumeMutation.isPending}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-xl shadow-xs transition-colors cursor-pointer disabled:opacity-50"
              >
                {resumeMutation.isPending ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Resuming…</span>
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5" />
                    <span>Resume Run</span>
                  </>
                )}
              </button>
            )}

            {run.status === 'waiting' && (
              <button
                type="button"
                onClick={() => setApprovalModalOpen(true)}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white text-xs font-semibold rounded-xl shadow-xs transition-colors cursor-pointer"
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                <span>Review Changes</span>
              </button>
            )}

            {actions.includes('export') && (
              <ExportDropdown
                workspaceId={workspaceId!}
                runId={run.id}
                workflowSlug={run.workflow_slug}
                variant="emerald"
                size="md"
              />
            )}

          </div>
        </div>
      </div>

      {/* Action Error Banner */}
      {actionError && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 text-xs rounded-xl p-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
            <span>{actionError}</span>
          </div>
          <button
            type="button"
            onClick={() => setActionError(null)}
            className="text-rose-600 hover:text-rose-900 font-bold px-2"
          >
            ×
          </button>
        </div>
      )}

      {/* 2a. Pre-HITL Remote Processing Banner */}
      {run.status === 'running' && run.current_stage === 'superdocs_approval' && (
        <div className="bg-blue-50/90 border border-blue-200 rounded-2xl p-5 shadow-xs flex items-center gap-3.5">
          <div className="w-10 h-10 rounded-xl bg-blue-100 text-blue-700 flex items-center justify-center shrink-0">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-blue-950">
              Preparing Human Review
            </h3>
            <p className="text-xs text-blue-800 mt-0.5">
              SuperDocs is processing the document and preparing change proposals. The review modal will open as soon as changes are ready.
            </p>
          </div>
        </div>
      )}

      {/* 2b. Human Review Required Banner (When run is waiting) */}
      {run.status === 'waiting' && (
        <div className="bg-amber-50/90 border border-amber-300 rounded-2xl p-5 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center shrink-0">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-amber-950">
                Waiting for Human Review
              </h3>
              <p className="text-xs text-amber-800 mt-0.5">
                The workflow has paused for human inspection ({claims.filter((c: any) => c.status === 'pending').length} pending change{claims.filter((c: any) => c.status === 'pending').length === 1 ? '' : 's'}). Review the proposed changes to continue.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setApprovalModalOpen(true)}
            className="inline-flex items-center justify-center gap-1.5 px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white text-xs font-bold rounded-xl shadow-xs transition-colors cursor-pointer shrink-0"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>Open Review Modal ({claims.filter((c: any) => c.status === 'pending').length})</span>
          </button>
        </div>
      )}

      {/* 3. Main 2-Column Content Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Stage Timeline (5 cols) */}
        <div className="lg:col-span-5">
          <StageTimeline stages={stages} currentStageName={run.current_stage} />
        </div>

        {/* Right Column: Cards Stack (7 cols) */}
        <div className="lg:col-span-7 flex flex-col space-y-6 min-h-0">
          {/* Card 1: Quality Check */}
          <div>
            <QualityGateResult workflowRunId={run.id} />
          </div>

          {/* Card 2: Run Summary */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 sm:p-6 shadow-xs space-y-4">
            <h3 className="text-sm font-bold text-slate-900 tracking-tight">Run Summary</h3>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-1">
              {/* Row 1 */}
              <div className="space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                  Status
                </span>
                <StatusBadge status={run.status} type="run" />
              </div>

              <div className="space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                  Stages
                </span>
                <span className="text-xs font-bold text-slate-800">
                  {completedStagesCount} / {totalStagesCount}
                </span>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                  Started at
                </span>
                <span className="text-xs font-semibold text-slate-700">
                  {formatDate(run.started_at || run.created_at)}
                </span>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                  Completed at
                </span>
                <span className="text-xs font-semibold text-slate-700">
                  {run.completed_at ? formatDate(run.completed_at) : (run.status === 'completed' ? 'Just now' : '—')}
                </span>
              </div>

              {/* Row 2 */}
              <div className="space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                  Total Time
                </span>
                <span className="text-xs font-bold text-slate-800">{totalTime}</span>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                  Workflow Type
                </span>
                <span className="text-xs font-semibold text-slate-700">{workflowLabel}</span>
              </div>

              <div className="space-y-1 col-span-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                  Run ID
                </span>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono font-semibold text-slate-800 truncate">
                    {run.id}
                  </span>
                  <button
                    type="button"
                    onClick={handleCopyId}
                    title="Copy Run ID"
                    className="text-slate-400 hover:text-slate-600 cursor-pointer"
                  >
                    {copiedId ? (
                      <Check className="w-3.5 h-3.5 text-emerald-600" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Card 3: Retrieved Evidence - Constrained compact height with internal scrolling */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 sm:p-6 shadow-xs flex flex-col h-[554px] min-h-0 overflow-hidden">
            {/* Pinned Card Header */}
            <div className="shrink-0 pb-3 border-b border-slate-100 mb-3">
              <h3 className="text-sm font-bold text-slate-900 tracking-tight">
                Retrieved Evidence
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Top source passages used during this run
              </p>
            </div>

            {/* Scrollable Card Content */}
            <div className="min-h-0 flex-1 overflow-hidden">
              {evidenceQuery.isLoading ? (
                <div className="space-y-2 h-full">
                  <Skeleton className="h-16 w-full rounded-xl" />
                  <Skeleton className="h-16 w-full rounded-xl" />
                </div>
              ) : evidence.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-center text-slate-400 text-xs">
                  <FileText className="w-6 h-6 mx-auto mb-1.5 text-slate-300" />
                  <p>No evidence items retrieved for this run yet.</p>
                </div>
              ) : (
                <div className="h-full min-h-0 overflow-y-auto space-y-3 pr-2">
                  {evidence.map((item) => (
                    <div
                      key={item.id}
                      className="bg-blue-50/40 border border-blue-100 rounded-xl p-3.5 space-y-1.5 text-xs shrink-0"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-bold text-blue-900 uppercase text-[10px] tracking-wider">
                          {item.evidence_type.replace(/_/g, ' ')}
                        </span>
                        {item.relevance_score != null && (
                          <span className="text-xs font-semibold text-blue-600">
                            {Math.round(item.relevance_score * 100)}% relevant
                          </span>
                        )}
                      </div>
                      <p className="text-slate-700 leading-relaxed font-normal">
                        {item.extracted_text}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 5. Human Approval Modal */}
      <HumanApprovalModal
        open={approvalModalOpen}
        onClose={() => setApprovalModalOpen(false)}
        claims={claims}
        runId={run.id}
        startedAt={run.started_at ?? undefined}
        error={actionError}
        onApprove={(claimId) => approveClaimMutation.mutate(claimId)}
        onReject={(claimId) => rejectClaimMutation.mutate(claimId)}
        onApproveAll={() => approveAllClaimsMutation.mutate()}
        isActing={approveClaimMutation.isPending || rejectClaimMutation.isPending}
        isApprovingAll={approveAllClaimsMutation.isPending}
      />

      {/* 6. Kill Confirmation Dialog */}
      <ConfirmDialog
        open={killConfirmOpen}
        title="Kill workflow run"
        description={`Stop the ${workflowLabel} run? This cannot be undone.`}
        confirmLabel="Kill run"
        destructive
        onConfirm={() => cancelMutation.mutate()}
        onCancel={() => setKillConfirmOpen(false)}
      />
    </div>
  )
}
