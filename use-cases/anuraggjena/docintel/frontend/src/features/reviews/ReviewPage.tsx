import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ClipboardCheck, AlertCircle } from 'lucide-react'
import { reviewApi, type Claim } from '@/core/api/reviewApi'
import { runsApi } from '@/core/api/workflowApi'
import { documentApi } from '@/core/api/documentApi'
import { useAuth } from '@/core/auth/AuthContext'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { ReviewSkeleton } from '@/shared/components/skeletons/ReviewSkeleton'
import { Button } from '@/shared/components/ui/button'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { ExportButton } from '../exports/ExportButton'
import { parseReviewClaim } from './superdocsClaim'
import { WorkflowInfoBar } from './WorkflowInfoBar'
import { DocumentComparisonView } from './DocumentComparisonView'
import { ChangeDetailsSidebar } from './ChangeDetailsSidebar'
import { ReviewActionBar } from './ReviewActionBar'
import { useReviewLiveUpdates } from './useReviewLiveUpdates'

const DECIDED_STATUSES = new Set(['approved', 'rejected', 'applied', 'rejected_applied'])

function orderClaimsForNavigation(claims: Claim[]): Claim[] {
  const pending = claims.filter((claim) => !DECIDED_STATUSES.has(claim.status))
  const decided = claims.filter((claim) => DECIDED_STATUSES.has(claim.status))
  return [...pending, ...decided]
}

function getSubtitleMessage(
  reviewStatus: string,
  totalClaims: number,
  pendingCount: number
): string {
  if (totalClaims === 0) {
    return 'No changes require your review.'
  }
  if (reviewStatus === 'rejected') {
    return 'Change rejected. Workflow will not incorporate these proposed edits.'
  }
  if (reviewStatus === 'approved') {
    return 'All changes approved. Document is ready for export and downstream processing.'
  }
  if (pendingCount > 0) {
    return `${pendingCount} of ${totalClaims} proposed change${totalClaims > 1 ? 's' : ''} pending review.`
  }
  return 'All changes reviewed.'
}

export function ReviewPage() {
  const { workspaceId, reviewId } = useParams<{ workspaceId: string; reviewId: string }>()
  const { user } = useAuth()
  const queryClient = useQueryClient()

  const [activeChangeIndex, setActiveChangeIndex] = useState(0)
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'approved' | 'rejected'>('all')
  const [claimActionError, setClaimActionError] = useState<string | null>(null)
  const [approveAllOpen, setApproveAllOpen] = useState(false)
  const [rejectClaimOpen, setRejectClaimOpen] = useState(false)

  const canDecideClaims =
    user?.role === 'reviewer' || user?.role === 'admin' || user?.role === 'user'

  const reviewQuery = useQuery({
    queryKey: ['review', reviewId],
    queryFn: () => reviewApi.getReview(reviewId!),
    enabled: !!reviewId,
  })

  const claimsQuery = useQuery({
    queryKey: ['claims', reviewId],
    queryFn: () => reviewApi.listReviewClaims(reviewId!),
    enabled: !!reviewId,
  })

  const review = reviewQuery.data

  const runClaimsQuery = useQuery({
    queryKey: ['run-claims', workspaceId, review?.workflow_run_id],
    queryFn: () => runsApi.getClaims(workspaceId!, review!.workflow_run_id),
    enabled: !!workspaceId && !!review?.workflow_run_id,
  })

  const runQuery = useQuery({
    queryKey: ['run', workspaceId, review?.workflow_run_id],
    queryFn: () => runsApi.get(workspaceId!, review!.workflow_run_id),
    enabled: !!workspaceId && !!review?.workflow_run_id,
  })

  const documentsQuery = useQuery({
    queryKey: ['documents', workspaceId],
    queryFn: () => documentApi.list(workspaceId!),
    enabled: !!workspaceId,
  })

  useReviewLiveUpdates(reviewId!, review?.status)

  // Merge direct review claims and run claims into a complete list
  const allClaims = useMemo(() => {
    const directClaims = claimsQuery.data ?? []
    const runClaims = (runClaimsQuery.data ?? []) as unknown as Claim[]
    const map = new Map<string, Claim>()
    for (const c of directClaims) {
      map.set(c.id, c)
    }
    for (const c of runClaims) {
      if (!map.has(c.id)) {
        map.set(c.id, c)
      }
    }
    return Array.from(map.values())
  }, [claimsQuery.data, runClaimsQuery.data])

  const navigationClaims = useMemo(() => orderClaimsForNavigation(allClaims), [allClaims])

  const pendingCount = allClaims.filter((claim) => !DECIDED_STATUSES.has(claim.status)).length
  const approvedCount = allClaims.filter((claim) => claim.status === 'approved' || claim.status === 'applied').length
  const rejectedCount = allClaims.filter((claim) => claim.status === 'rejected' || claim.status === 'rejected_applied').length

  const filteredClaims = useMemo(() => {
    if (statusFilter === 'pending') {
      return navigationClaims.filter((c) => !DECIDED_STATUSES.has(c.status))
    }
    if (statusFilter === 'approved') {
      return navigationClaims.filter((c) => c.status === 'approved' || c.status === 'applied')
    }
    if (statusFilter === 'rejected') {
      return navigationClaims.filter((c) => c.status === 'rejected' || c.status === 'rejected_applied')
    }
    return navigationClaims
  }, [navigationClaims, statusFilter])

  const activeClaim = navigationClaims[activeChangeIndex] ?? null
  const activeParsedClaim = useMemo(
    () => (activeClaim ? parseReviewClaim(activeClaim) : null),
    [activeClaim]
  )

  useEffect(() => {
    if (activeChangeIndex >= navigationClaims.length && navigationClaims.length > 0) {
      setActiveChangeIndex(Math.max(0, navigationClaims.length - 1))
    }
  }, [activeChangeIndex, navigationClaims.length])

  const approveClaimMutation = useMutation({
    mutationFn: reviewApi.approveClaim,
    onSuccess: () => {
      setClaimActionError(null)
      void queryClient.invalidateQueries({ queryKey: ['claims', reviewId] })
      void queryClient.invalidateQueries({ queryKey: ['run-claims', workspaceId, review?.workflow_run_id] })
      void queryClient.invalidateQueries({ queryKey: ['review', reviewId] })
      if (activeChangeIndex < navigationClaims.length - 1) {
        setActiveChangeIndex((i) => i + 1)
      }
    },
    onError: (error: Error) => {
      setClaimActionError(error.message || 'Failed to approve change')
    },
  })

  const rejectClaimMutation = useMutation({
    mutationFn: reviewApi.rejectClaim,
    onSuccess: () => {
      setClaimActionError(null)
      void queryClient.invalidateQueries({ queryKey: ['claims', reviewId] })
      void queryClient.invalidateQueries({ queryKey: ['run-claims', workspaceId, review?.workflow_run_id] })
      void queryClient.invalidateQueries({ queryKey: ['review', reviewId] })
      if (activeChangeIndex < navigationClaims.length - 1) {
        setActiveChangeIndex((i) => i + 1)
      }
    },
    onError: (error: Error) => {
      setClaimActionError(error.message || 'Failed to reject change')
    },
  })

  const approveAllMutation = useMutation({
    mutationFn: async () => {
      try {
        await reviewApi.approveAllReviewClaims(reviewId!)
      } catch {
        await reviewApi.updateReview(reviewId!, { status: 'approved' })
      }
    },
    onSuccess: () => {
      setClaimActionError(null)
      void queryClient.invalidateQueries({ queryKey: ['review', reviewId] })
      void queryClient.invalidateQueries({ queryKey: ['claims', reviewId] })
      void queryClient.invalidateQueries({ queryKey: ['run-claims', workspaceId, review?.workflow_run_id] })
    },
    onError: (error: Error) => {
      setClaimActionError(error.message || 'Failed to approve review')
    },
  })

  const resumeWorkflowMutation = useMutation({
    mutationFn: () => runsApi.resume(workspaceId!, review!.workflow_run_id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['run', workspaceId, review?.workflow_run_id] })
    },
  })

  if (reviewQuery.isLoading || claimsQuery.isLoading) {
    return <ReviewSkeleton />
  }

  if (reviewQuery.isError || !review) {
    return (
      <ErrorState
        title="Couldn't load this review"
        description="We couldn't fetch the review details. Please try again."
        onRetry={() => {
          void reviewQuery.refetch()
          void claimsQuery.refetch()
        }}
        error={reviewQuery.error}
      />
    )
  }

  if (claimsQuery.isError) {
    return (
      <ErrorState
        title="Couldn't load review changes"
        description="We couldn't fetch the changes for this review. Please try again."
        onRetry={() => void claimsQuery.refetch()}
        error={claimsQuery.error}
      />
    )
  }

  if (navigationClaims.length === 0 || !activeClaim || !activeParsedClaim) {
    return (
      <EmptyState
        icon={ClipboardCheck}
        title="No changes to review"
        description="This review doesn't have any document changes that need your decision."
      />
    )
  }

  const backHref = `/workspace/${workspaceId}/runs/${review.workflow_run_id}`
  const subtitle = getSubtitleMessage(review.status, navigationClaims.length, pendingCount)
  const showApproveAll =
    canDecideClaims &&
    pendingCount > 0 &&
    review.status !== 'approved' &&
    review.status !== 'rejected'

  // Non-image document name resolution
  const primaryDoc = documentsQuery.data?.find(
    (d) => !d.filename.match(/\.(png|jpe?g|gif|webp|svg)$/i)
  )

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 space-y-6">
      {/* Top Navigation Link */}
      <div className="flex items-center justify-between">
        <Link
          to={backHref}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to workflow run
        </Link>
      </div>

      {/* Main Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
              Document Review
            </h1>
            <span className="rounded-md bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">
              Change {activeChangeIndex + 1} of {navigationClaims.length}
            </span>
            <StatusBadge status={review.status} type="review" />
          </div>
          <p className="text-xs text-muted-foreground sm:text-sm">{subtitle}</p>
        </div>

        <div className="flex items-center gap-3">
          <ExportButton reviewId={review.id} workspaceId={review.workspace_id} />
          {showApproveAll && (
            <Button
              type="button"
              size="sm"
              onClick={() => setApproveAllOpen(true)}
              disabled={approveAllMutation.isPending}
              className="text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs cursor-pointer"
            >
              {approveAllMutation.isPending ? 'Approving…' : `Approve all (${pendingCount})`}
            </Button>
          )}
        </div>
      </div>

      {/* Workflow Info Bar */}
      <WorkflowInfoBar
        runId={review.workflow_run_id}
        workflowSlug={runQuery.data?.workflow_slug}
        stageName={runQuery.data?.current_stage || activeParsedClaim.chunkId || 'Human Review'}
        requestedAt={review.created_at}
        requestedBy={runQuery.data?.created_by || 'System'}
        reviewStatus={review.status}
      />

      {/* Action Error Banner */}
      {claimActionError && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{claimActionError}</span>
        </div>
      )}

      {/* Main Master-Detail Layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12 items-start">
        {/* Left/Master List Column */}
        <div className="lg:col-span-4 xl:col-span-4 space-y-3">
          {/* Status Filter Tabs */}
          <div className="flex items-center gap-1.5 p-1 bg-muted/50 rounded-lg border border-border text-xs">
            <button
              type="button"
              onClick={() => setStatusFilter('all')}
              className={`flex-1 py-1 px-2 rounded-md font-semibold text-center transition-colors cursor-pointer ${
                statusFilter === 'all'
                  ? 'bg-background text-foreground shadow-xs'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              All ({allClaims.length})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('pending')}
              className={`flex-1 py-1 px-2 rounded-md font-semibold text-center transition-colors cursor-pointer ${
                statusFilter === 'pending'
                  ? 'bg-background text-foreground shadow-xs'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              Pending ({pendingCount})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('approved')}
              className={`flex-1 py-1 px-2 rounded-md font-semibold text-center transition-colors cursor-pointer ${
                statusFilter === 'approved'
                  ? 'bg-background text-foreground shadow-xs'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              Approved ({approvedCount})
            </button>
            {rejectedCount > 0 && (
              <button
                type="button"
                onClick={() => setStatusFilter('rejected')}
                className={`flex-1 py-1 px-2 rounded-md font-semibold text-center transition-colors cursor-pointer ${
                  statusFilter === 'rejected'
                    ? 'bg-background text-foreground shadow-xs'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                Rejected ({rejectedCount})
              </button>
            )}
          </div>

          {/* Changes Master List */}
          <div className="flex flex-col gap-2 max-h-[640px] overflow-y-auto pr-1">
            {filteredClaims.map((claim) => {
              const parsed = parseReviewClaim(claim)
              const originalIndex = navigationClaims.findIndex((c) => c.id === claim.id)
              const isSelected = originalIndex === activeChangeIndex

              return (
                <button
                  key={claim.id}
                  type="button"
                  onClick={() => setActiveChangeIndex(originalIndex)}
                  className={`flex flex-col text-left p-3 rounded-xl border transition-all cursor-pointer ${
                    isSelected
                      ? 'border-primary bg-primary/5 ring-1 ring-primary shadow-xs'
                      : 'border-border bg-card hover:bg-muted/40'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[11px] font-bold font-mono text-muted-foreground shrink-0">
                        #{originalIndex + 1}
                      </span>
                      <span
                        className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          parsed.changeType === 'added'
                            ? 'bg-emerald-100 text-emerald-800'
                            : parsed.changeType === 'removed'
                              ? 'bg-rose-100 text-rose-800'
                              : 'bg-amber-100 text-amber-800'
                        }`}
                      >
                        {parsed.changeType === 'added'
                          ? '+ Added'
                          : parsed.changeType === 'removed'
                            ? '- Removed'
                            : '✏ Modified'}
                      </span>
                    </div>
                    <StatusBadge status={claim.status} type="claim" />
                  </div>

                  <p className="text-xs font-semibold text-foreground line-clamp-1">
                    {parsed.section}
                  </p>

                  <p className="text-[11px] text-muted-foreground line-clamp-1 mt-0.5">
                    {parsed.newText || parsed.oldText || parsed.aiExplanation || 'Proposed update'}
                  </p>
                </button>
              )
            })}
          </div>
        </div>

        {/* Center/Right Detail Comparison & Actions */}
        <div className="lg:col-span-8 xl:col-span-8 space-y-6">
          <DocumentComparisonView claim={activeParsedClaim} />

          <ReviewActionBar
            currentIndex={activeChangeIndex}
            totalChanges={navigationClaims.length}
            activeClaim={activeParsedClaim}
            canDecide={canDecideClaims}
            isApproving={approveClaimMutation.isPending}
            isRejecting={rejectClaimMutation.isPending}
            isResuming={resumeWorkflowMutation.isPending}
            showResumeWorkflow={
              review.status === 'approved' && runQuery.data?.status === 'waiting_for_approval'
            }
            onPrevious={() => setActiveChangeIndex((i) => Math.max(0, i - 1))}
            onNext={() => setActiveChangeIndex((i) => Math.min(navigationClaims.length - 1, i + 1))}
            onApprove={() => approveClaimMutation.mutate(activeClaim.id)}
            onReject={() => setRejectClaimOpen(true)}
            onResumeWorkflow={() => resumeWorkflowMutation.mutate()}
          />

          <ChangeDetailsSidebar
            claim={activeParsedClaim}
            reviewId={review.id}
            requestedAt={review.created_at}
            documentName={
              activeParsedClaim.documentName ||
              primaryDoc?.filename ||
              'Tariff Product Specification'
            }
          />
        </div>
      </div>

      {/* Reject Confirmation Modal */}
      <ConfirmDialog
        open={rejectClaimOpen}
        title="Reject this change?"
        description="Rejecting this change means the document will keep its original text for this section."
        confirmLabel="Reject change"
        destructive
        onConfirm={() => {
          setRejectClaimOpen(false)
          rejectClaimMutation.mutate(activeClaim.id)
        }}
        onCancel={() => setRejectClaimOpen(false)}
      />

      {/* Approve All Confirmation Modal */}
      <ConfirmDialog
        open={approveAllOpen}
        title="Approve all changes?"
        description={`This will approve all ${pendingCount} pending change${pendingCount > 1 ? 's' : ''} in this review. The workflow will proceed with the approved document updates.`}
        confirmLabel={`Approve all (${pendingCount})`}
        onConfirm={() => {
          setApproveAllOpen(false)
          approveAllMutation.mutate()
        }}
        onCancel={() => setApproveAllOpen(false)}
      />
    </div>
  )
}

