import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  BookOpen,
  ClipboardCheck,
  FileText,
  Play,
  Upload,
  Clock,
  FolderDown,
  Image as ImageIcon,
  ChevronRight,
  AlertCircle,
  Check,
  Ban,
  Users,
} from 'lucide-react'

import { workspaceApi } from '@/core/api/client'
import { documentApi } from '@/core/api/documentApi'
import { exportApi } from '@/core/api/exportApi'
import { knowledgeApi } from '@/core/api/knowledgeApi'
import { reviewApi } from '@/core/api/reviewApi'
import { runsApi } from '@/core/api/workflowApi'
import { useAuth } from '@/core/auth/AuthContext'
import { formatWorkflowSlug } from '@/core/labels'
import { ErrorState } from '@/shared/components/ErrorState'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { MetricCard } from './MetricCard'
import { StartWorkflowDialog } from '@/features/workflows/StartWorkflowDialog'
import { ScreenplayWorkspacePage } from '@/features/screenplay'

const ACTIVE_RUN_STATUSES = new Set(['running', 'in_progress', 'waiting', 'queued'])
const MAX_RECENT = 4

function formatCreatedDate(dateString: string): string {
  try {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return dateString
  }
}

function formatRelativeTime(dateString: string): string {
  try {
    const date = new Date(dateString)
    const now = new Date()
    const diffSecs = Math.floor((now.getTime() - date.getTime()) / 1000)
    if (diffSecs < 60) return 'Just now'
    const diffMins = Math.floor(diffSecs / 60)
    if (diffMins < 60) return `${diffMins} min${diffMins === 1 ? '' : 's'} ago`
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`
    const diffDays = Math.floor(diffHours / 24)
    if (diffDays < 30) return `${diffDays} day${diffDays === 1 ? '' : 's'} ago`
    return formatCreatedDate(dateString)
  } catch {
    return dateString
  }
}

function formatDocRoleBadge(role?: string, filename?: string): string {
  if (role === 'product_image' || (!role && filename?.match(/\.(png|jpg|jpeg|webp)$/i))) {
    return 'Product Image'
  }
  if (role === 'classification_ruling' || role === 'ruling') {
    return 'Classification Ruling'
  }
  if (role === 'product_spec' || role === 'product_specification' || role === 'product') {
    return 'Product Specification'
  }
  if (role) {
    return role
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ')
  }
  return 'Document'
}

function isImageFile(filename: string, role?: string): boolean {
  if (role === 'product_image') return true
  return /\.(png|jpg|jpeg|webp|gif|svg)$/i.test(filename)
}

function renderRunStatusBadge(status: string) {
  switch (status.toLowerCase()) {
    case 'completed':
    case 'succeeded':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200/60">
          <Check className="w-3.5 h-3.5 stroke-[2.5]" />
          <span>Completed</span>
        </span>
      )
    case 'blocked':
    case 'waiting':
    case 'in_review':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200/60">
          <AlertCircle className="w-3.5 h-3.5 stroke-[2.5]" />
          <span>Blocked</span>
        </span>
      )
    case 'cancelled':
    case 'canceled':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-orange-50 text-orange-700 border border-orange-200/60">
          <Ban className="w-3.5 h-3.5 stroke-[2.5]" />
          <span>Cancelled</span>
        </span>
      )
    case 'failed':
    case 'error':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-red-50 text-red-700 border border-red-200/60">
          <AlertCircle className="w-3.5 h-3.5 stroke-[2.5]" />
          <span>Failed</span>
        </span>
      )
    case 'running':
    case 'in_progress':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200/60">
          <Play className="w-3 h-3 fill-current stroke-[1.5]" />
          <span>Running</span>
        </span>
      )
    default:
      return (
        <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-200 capitalize">
          {status}
        </span>
      )
  }
}

export function OverviewPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const { accessToken } = useAuth()
  const [isStartWorkflowOpen, setIsStartWorkflowOpen] = useState(false)

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
  })

  const reviewsQuery = useQuery({
    queryKey: ['reviews', workspaceId],
    queryFn: () => reviewApi.listWorkspaceReviews(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const exportsQuery = useQuery({
    queryKey: ['exports', workspaceId],
    queryFn: () => exportApi.listByWorkspace(workspaceId!).catch(() => []),
    enabled: !!workspaceId && !!accessToken,
  })

  const knowledgeQuery = useQuery({
    queryKey: ['knowledge', workspaceId, workspaceQuery.data?.workflow_type],
    queryFn: () =>
      knowledgeApi.listByWorkspace(workspaceId!, {
        workflow_type: workspaceQuery.data?.workflow_type ?? undefined,
      }),
    enabled: !!workspaceId && !!accessToken && workspaceQuery.isSuccess,
  })

  const isLoading =
    workspaceQuery.isLoading ||
    documentsQuery.isLoading ||
    runsQuery.isLoading ||
    reviewsQuery.isLoading ||
    knowledgeQuery.isLoading

  const workspaceError = workspaceQuery.error
  const dataError =
    documentsQuery.error ??
    runsQuery.error ??
    reviewsQuery.error ??
    knowledgeQuery.error

  if (workspaceError || dataError) {
    return (
      <ErrorState
        title="Failed to load overview"
        description="We couldn't load workspace data. Please try again."
        onRetry={() => {
          void workspaceQuery.refetch()
          void documentsQuery.refetch()
          void runsQuery.refetch()
          void reviewsQuery.refetch()
          void exportsQuery.refetch()
          void knowledgeQuery.refetch()
        }}
        error={workspaceError ?? dataError}
      />
    )
  }

  const workspace = workspaceQuery.data

  if (workspace?.workflow_type === 'screenplay') {
    return <ScreenplayWorkspacePage />
  }
  const documents = documentsQuery.data ?? []
  const runs = runsQuery.data ?? []
  const reviews = reviewsQuery.data ?? []
  const exports = exportsQuery.data ?? []
  const knowledge = knowledgeQuery.data ?? []

  const activeRuns = runs.filter((r) => ACTIVE_RUN_STATUSES.has(r.status))
  const pendingReviews = reviews.filter((r) =>
    ['in_review', 'pending', 'awaiting_review', 'waiting'].includes(r.status)
  )

  const completedRunsCount = runs.filter((r) => r.status === 'completed').length
  const exportsCount = exports.length > 0 ? exports.length : completedRunsCount

  const recentRuns = [...runs]
    .sort(
      (a, b) =>
        new Date(b.created_at || b.started_at || 0).getTime() -
        new Date(a.created_at || a.started_at || 0).getTime()
    )
    .slice(0, MAX_RECENT)

  const recentDocuments = [...documents]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, MAX_RECENT)

  const recentPendingReviews = [...pendingReviews]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, MAX_RECENT)

  const recentKnowledge = [...knowledge]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, MAX_RECENT)

  const basePath = `/workspace/${workspaceId}`

  return (
    <div className="space-y-7">
      {/* 1. Header Section */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            {isLoading ? (
              <Skeleton className="h-9 w-64 rounded-lg" />
            ) : (
              <h1 className="text-3xl font-bold text-slate-900 tracking-tight">
                {workspace?.name || 'Workspace'}
              </h1>
            )}

            {workspace?.workflow_type && (
              <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-200/60">
                {formatWorkflowSlug(workspace.workflow_type)}
              </span>
            )}
          </div>

          <p className="text-xs sm:text-sm text-slate-500 mt-1.5">
            {workspace?.created_at && (
              <>Created on {formatCreatedDate(workspace.created_at)}</>
            )}
            {workspace?.updated_at && (
              <> • Last updated {formatRelativeTime(workspace.updated_at)}</>
            )}
          </p>
        </div>

        {/* Start workflow Button */}
        <div>
          <button
            type="button"
            onClick={() => setIsStartWorkflowOpen(true)}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-sm font-semibold rounded-lg shadow-sm transition-all duration-150 cursor-pointer"
          >
            <Play className="w-4 h-4 fill-current stroke-[1.5]" />
            <span>Start workflow</span>
          </button>
        </div>
      </div>

      {/* 2. Five Summary Metric Cards */}
      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          <MetricCard
            label="Documents"
            count={documents.length}
            subtext="Total uploaded"
            icon={FileText}
            iconColor="text-blue-600"
            iconBgColor="bg-blue-50 border-blue-100"
          />
          <MetricCard
            label="Active Runs"
            count={activeRuns.length}
            subtext="Currently running"
            icon={Play}
            iconColor="text-blue-600"
            iconBgColor="bg-blue-50 border-blue-100"
          />
          <MetricCard
            label="Pending Reviews"
            count={pendingReviews.length}
            subtext="Awaiting human review"
            icon={Clock}
            iconColor="text-purple-600"
            iconBgColor="bg-purple-50 border-purple-100"
          />
          <MetricCard
            label="Knowledge Entries"
            count={knowledge.length}
            subtext="Generated"
            icon={BookOpen}
            iconColor="text-emerald-600"
            iconBgColor="bg-emerald-50 border-emerald-100"
          />
          <MetricCard
            label="Exports"
            count={exportsCount}
            subtext="Generated"
            icon={FolderDown}
            iconColor="text-amber-600"
            iconBgColor="bg-amber-50 border-amber-100"
          />
        </div>
      )}

      {/* 3. 2x2 Panels Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Panel 1: Recent Workflow Runs */}
        <div className="bg-white border border-slate-200/90 rounded-2xl shadow-sm overflow-hidden flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <h2 className="text-base font-bold text-slate-900 tracking-tight">
                Recent Workflow Runs
              </h2>
              <Link
                to={`${basePath}/runs`}
                className="text-sm font-semibold text-blue-600 hover:text-blue-700 transition-colors"
              >
                View all runs
              </Link>
            </div>

            {isLoading ? (
              <div className="p-6 space-y-4">
                <Skeleton className="h-14 rounded-xl" />
                <Skeleton className="h-14 rounded-xl" />
                <Skeleton className="h-14 rounded-xl" />
              </div>
            ) : recentRuns.length === 0 ? (
              <div className="p-8 text-center">
                <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-2">
                  <Play className="w-5 h-5 fill-current" />
                </div>
                <p className="text-sm font-semibold text-slate-900">No workflow runs yet</p>
                <p className="text-xs text-slate-500 mt-0.5 mb-4">
                  Start a workflow to process your documents.
                </p>
                <button
                  type="button"
                  onClick={() => setIsStartWorkflowOpen(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors cursor-pointer"
                >
                  Start workflow
                </button>
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {recentRuns.map((run) => (
                  <Link
                    key={run.id}
                    to={`${basePath}/runs/${run.id}`}
                    className="flex items-center justify-between gap-4 px-6 py-3.5 hover:bg-slate-50/70 transition-colors group"
                  >
                    <div className="flex items-center gap-3.5 min-w-0">
                      <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 border border-blue-100 flex items-center justify-center shrink-0">
                        <Play className="w-4 h-4 fill-current stroke-[1.5]" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-slate-900 leading-tight group-hover:text-blue-600 transition-colors">
                          {formatWorkflowSlug(run.workflow_slug || workspace?.workflow_type || 'Tariff Classification')}
                        </p>
                        <p className="text-xs text-slate-500 font-mono mt-0.5 truncate">
                          Run ID: {run.id}
                        </p>
                        <p className="text-[11px] text-slate-400 mt-0.5">
                          {run.current_stage ? `${run.current_stage} • ` : ''}
                          {formatRelativeTime(run.started_at || run.created_at)}
                        </p>
                      </div>
                    </div>
                    <div className="shrink-0 flex items-center">
                      {renderRunStatusBadge(run.status)}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>

          <div className="p-3 bg-slate-50/50 border-t border-slate-100 text-center">
            <Link
              to={`${basePath}/runs`}
              className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700 transition-colors"
            >
              <span>View all runs</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>

        {/* Panel 2: Recent Documents */}
        <div className="bg-white border border-slate-200/90 rounded-2xl shadow-sm overflow-hidden flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <h2 className="text-base font-bold text-slate-900 tracking-tight">
                Recent Documents
              </h2>
              <Link
                to={`${basePath}/documents`}
                className="text-sm font-semibold text-blue-600 hover:text-blue-700 transition-colors"
              >
                View all documents
              </Link>
            </div>

            {isLoading ? (
              <div className="p-6 space-y-4">
                <Skeleton className="h-14 rounded-xl" />
                <Skeleton className="h-14 rounded-xl" />
                <Skeleton className="h-14 rounded-xl" />
              </div>
            ) : recentDocuments.length === 0 ? (
              <div className="p-8 text-center">
                <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-2">
                  <FileText className="w-5 h-5" />
                </div>
                <p className="text-sm font-semibold text-slate-900">No documents yet</p>
                <p className="text-xs text-slate-500 mt-0.5 mb-4">
                  Upload product documents to begin classification.
                </p>
                <Link
                  to={`${basePath}/documents`}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors"
                >
                  <Upload className="w-3.5 h-3.5" />
                  <span>Upload documents</span>
                </Link>
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {recentDocuments.map((doc) => {
                  const isImg = isImageFile(doc.filename, doc.document_role)
                  return (
                    <Link
                      key={doc.id}
                      to={`${basePath}/documents`}
                      className="flex items-center justify-between gap-4 px-6 py-3.5 hover:bg-slate-50/70 transition-colors group"
                    >
                      <div className="flex items-center gap-3.5 min-w-0">
                        <div
                          className={cn(
                            'w-9 h-9 rounded-xl border flex items-center justify-center shrink-0',
                            isImg
                              ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
                              : 'bg-red-50 text-red-600 border-red-100'
                          )}
                        >
                          {isImg ? (
                            <ImageIcon className="w-4 h-4 stroke-[2]" />
                          ) : (
                            <FileText className="w-4 h-4 stroke-[2]" />
                          )}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-slate-900 leading-tight truncate group-hover:text-blue-600 transition-colors">
                            {doc.filename}
                          </p>
                          <p className="text-xs text-slate-400 mt-0.5">
                            {formatRelativeTime(doc.created_at)}
                          </p>
                        </div>
                      </div>
                      <div className="shrink-0">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200/60">
                          {formatDocRoleBadge(doc.document_role, doc.filename)}
                        </span>
                      </div>
                    </Link>
                  )
                })}
              </div>
            )}
          </div>

          <div className="p-3 bg-slate-50/50 border-t border-slate-100 text-center">
            <Link
              to={`${basePath}/documents`}
              className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700 transition-colors"
            >
              <span>View all documents</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>

        {/* Panel 3: Pending Reviews */}
        <div className="bg-white border border-slate-200/90 rounded-2xl shadow-sm overflow-hidden flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <h2 className="text-base font-bold text-slate-900 tracking-tight">
                Pending Reviews
              </h2>
              <Link
                to={`${basePath}/reviews`}
                className="text-sm font-semibold text-blue-600 hover:text-blue-700 transition-colors"
              >
                View all reviews
              </Link>
            </div>

            {isLoading ? (
              <div className="p-6 space-y-4">
                <Skeleton className="h-20 rounded-xl" />
              </div>
            ) : recentPendingReviews.length === 0 ? (
              <div className="p-8 text-center">
                <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-2">
                  <ClipboardCheck className="w-5 h-5 stroke-[1.75]" />
                </div>
                <p className="text-sm font-semibold text-slate-900">No pending reviews</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  Reviews will appear here when a workflow needs human input.
                </p>
              </div>
            ) : (
              <div className="p-5 space-y-3">
                {recentPendingReviews.map((review) => (
                  <Link
                    key={review.id}
                    to={`${basePath}/reviews/${review.id}`}
                    className="block rounded-xl border-l-4 border-l-amber-400 bg-amber-50/40 border border-slate-200/80 p-4 hover:bg-amber-50/70 transition-all group"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 border border-blue-100 flex items-center justify-center shrink-0">
                          <Users className="w-4 h-4 stroke-[2]" />
                        </div>
                        <div>
                          <p className="text-sm font-bold text-slate-900 leading-tight group-hover:text-blue-600 transition-colors">
                            SuperDocs Change
                          </p>
                          <p className="text-xs text-slate-500 font-mono mt-0.5">
                            Change ID: {review.id}
                          </p>
                        </div>
                      </div>

                      <div className="text-right shrink-0">
                        <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-200/60">
                          Requires review
                        </span>
                        <p className="text-[11px] text-slate-400 mt-1">
                          {formatRelativeTime(review.created_at)}
                        </p>
                      </div>
                    </div>

                    <p className="text-xs text-slate-600 mt-2.5 leading-relaxed">
                      {review.notes || 'Review and approve changes for the Tariff Classification Memo.'}
                    </p>
                  </Link>
                ))}
              </div>
            )}
          </div>

          <div className="p-3 bg-slate-50/50 border-t border-slate-100 text-center">
            <Link
              to={`${basePath}/reviews`}
              className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700 transition-colors"
            >
              <span>View all reviews</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>

        {/* Panel 4: Recent Knowledge */}
        <div className="bg-white border border-slate-200/90 rounded-2xl shadow-sm overflow-hidden flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <h2 className="text-base font-bold text-slate-900 tracking-tight">
                Recent Knowledge
              </h2>
              <Link
                to={`${basePath}/knowledge`}
                className="text-sm font-semibold text-blue-600 hover:text-blue-700 transition-colors"
              >
                View all knowledge
              </Link>
            </div>

            {isLoading ? (
              <div className="p-6 space-y-4">
                <Skeleton className="h-16 rounded-xl" />
              </div>
            ) : recentKnowledge.length === 0 ? (
              <div className="p-8 text-center">
                <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-2">
                  <BookOpen className="w-5 h-5 stroke-[1.75]" />
                </div>
                <p className="text-sm font-semibold text-slate-900">No knowledge entries yet</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  Knowledge will appear here when workflows complete.
                </p>
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {recentKnowledge.map((entry) => (
                  <Link
                    key={entry.id}
                    to={`${basePath}/knowledge`}
                    className="block px-6 py-4 hover:bg-slate-50/70 transition-colors group"
                  >
                    <p className="text-xs font-semibold text-slate-800 line-clamp-2 leading-relaxed group-hover:text-blue-600 transition-colors">
                      {entry.content}
                    </p>
                    <p className="text-[11px] text-slate-400 mt-1">
                      {formatRelativeTime(entry.created_at)}
                    </p>
                  </Link>
                ))}
              </div>
            )}
          </div>

          <div className="p-3 bg-slate-50/50 border-t border-slate-100 text-center">
            <Link
              to={`${basePath}/knowledge`}
              className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700 transition-colors"
            >
              <span>View all knowledge</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      </div>

      {/* Start Workflow Dialog Modal */}
      {workspaceId && (
        <StartWorkflowDialog
          open={isStartWorkflowOpen}
          onOpenChange={setIsStartWorkflowOpen}
          workspaceId={workspaceId}
          documents={documents}
          workspaceWorkflowType={workspace?.workflow_type}
        />
      )}
    </div>
  )
}


