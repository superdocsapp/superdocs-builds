import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2 } from 'lucide-react'
import { screenplayApi } from '@/core/api/screenplayApi'
import { ExportDropdown } from '@/features/exports/ExportDropdown'
import { ChangeNavigator } from '@/features/reviews/ChangeNavigator'
import { ReviewShell } from '@/features/reviews/ReviewShell'
import { ErrorState } from '@/shared/components/ErrorState'
import { ReviewSkeleton } from '@/shared/components/skeletons/ReviewSkeleton'
import { Button } from '@/shared/components/ui/button'
import { FormattingItemList } from './FormattingItemList'
import { ScreenplayItemInspector } from './ScreenplayItemInspector'

function deriveReviewStatus(pending: number, rejected: number, total: number): string {
  if (total === 0) return 'approved'
  if (pending > 0) return 'in_review'
  if (rejected > 0) return 'rejected'
  return 'approved'
}

function buildStatusMessage(pending: number, approved: number, rejected: number, total: number): string {
  if (total === 0) return '0 pending · 0 approved · 0 rejected across 0 proposed changes'
  const parts = [
    `${pending} pending`,
    `${approved} approved`,
    `${rejected} rejected`,
  ]
  return `${parts.join(' · ')} across ${total} proposed changes`
}

export function ScreenplayReviewPage() {
  const { workspaceId, runId } = useParams<{ workspaceId: string; runId: string }>()
  const queryClient = useQueryClient()

  const [activeIndex, setActiveIndex] = useState(0)
  const [regenerating, setRegenerating] = useState(false)

  const itemsQuery = useQuery({
    queryKey: ['screenplay-items', runId],
    queryFn: () => screenplayApi.listItems(runId!),
    enabled: !!runId,
    refetchInterval: regenerating ? 2000 : false,
  })

  // Filter only items that represent ACTUAL proposed changes in stable element order
  const navigationItems = useMemo(() => {
    const all = itemsQuery.data ?? []
    return all
      .filter(
        (item) => item.change_type !== 'no_change' || item.status === 'pending' || item.status === 'rejected'
      )
      .sort((a, b) => (a.element_index ?? 0) - (b.element_index ?? 0))
  }, [itemsQuery.data])

  const pending = navigationItems.filter((item) => item.status === 'pending').length
  const approved = navigationItems.filter((item) => item.status === 'approved').length
  const rejected = navigationItems.filter((item) => item.status === 'rejected').length
  const activeItem = navigationItems[activeIndex] ?? null

  useEffect(() => {
    if (activeIndex >= navigationItems.length && navigationItems.length > 0) {
      setActiveIndex(Math.max(0, navigationItems.length - 1))
    }
  }, [activeIndex, navigationItems.length])

  const invalidateItems = () => {
    void queryClient.invalidateQueries({ queryKey: ['screenplay-items', runId] })
    void queryClient.invalidateQueries({ queryKey: ['reviews', workspaceId] })
    void queryClient.invalidateQueries({ queryKey: ['reviews'] })
    void queryClient.invalidateQueries({ queryKey: ['workspace-reviews', workspaceId] })
    void queryClient.invalidateQueries({ queryKey: ['runs', workspaceId] })
    void queryClient.invalidateQueries({ queryKey: ['run', workspaceId, runId] })
    void queryClient.invalidateQueries({ queryKey: ['screenplays', workspaceId] })
    void queryClient.invalidateQueries({ queryKey: ['screenplay-library'] })
  }

  const approveMutation = useMutation({
    mutationFn: (itemId: string) => screenplayApi.approveItem(runId!, itemId),
    onSuccess: invalidateItems,
  })

  const rejectMutation = useMutation({
    mutationFn: ({ itemId, comment }: { itemId: string; comment?: string }) =>
      screenplayApi.rejectItem(runId!, itemId, comment),
    onSuccess: invalidateItems,
  })

  const approveAllMutation = useMutation({
    mutationFn: () => screenplayApi.approveAll(runId!),
    onSuccess: invalidateItems,
  })

  const handleRegenerate = async () => {
    if (!runId) return
    setRegenerating(true)
    try {
      await screenplayApi.regenerate(runId)
      setTimeout(() => {
        invalidateItems()
        setRegenerating(false)
      }, 3000)
    } catch {
      setRegenerating(false)
    }
  }

  if (itemsQuery.isLoading) {
    return <ReviewSkeleton />
  }

  if (itemsQuery.isError || !runId || !workspaceId) {
    return (
      <ErrorState
        title="Couldn't load screenplay review"
        description="We couldn't fetch the formatting items for this run. Please try again."
        onRetry={() => {
          void itemsQuery.refetch()
        }}
        error={itemsQuery.error}
      />
    )
  }

  const backHref = `/workspace/${workspaceId}/runs/${runId}`
  const reviewStatus = deriveReviewStatus(pending, rejected, navigationItems.length)
  const statusMessage = buildStatusMessage(pending, approved, rejected, navigationItems.length)

  // Empty state when there are 0 proposed formatting changes
  if (navigationItems.length === 0) {
    return (
      <div className="flex min-h-[calc(100vh-8rem)] flex-col rounded-lg border bg-background">
        <header className="flex flex-col gap-3 border-b px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <Link
              to={backHref}
              className="inline-flex text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              ← Back to screenplay
            </Link>
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-semibold">Document Review</h1>
              <span className="rounded bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
                Approved
              </span>
            </div>
            <p className="text-xs text-muted-foreground">{statusMessage}</p>
          </div>
          <div className="flex items-center gap-2">
            <ExportDropdown
              workspaceId={workspaceId}
              runId={runId}
              workflowSlug="screenplay"
              variant="outline"
              size="sm"
            />
          </div>
        </header>

        <div className="flex flex-1 flex-col items-center justify-center p-12 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400">
            <CheckCircle2 className="h-7 w-7" />
          </div>
          <h2 className="text-base font-semibold text-foreground">No formatting changes proposed</h2>
          <p className="mt-2 max-w-md text-xs text-muted-foreground">
            The document conforms completely to screenplay standards. Every element is already correctly styled, so no human approvals are required.
          </p>
          <div className="mt-6 flex items-center gap-3">
            <ExportDropdown
              workspaceId={workspaceId}
              runId={runId}
              workflowSlug="screenplay"
              variant="primary"
              size="sm"
            />
            <Link to={backHref}>
              <Button type="button" variant="outline" size="sm">
                Return to Workspace
              </Button>
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <ReviewShell
      backHref={backHref}
      reviewStatus={reviewStatus}
      changeIndex={activeIndex}
      totalChanges={navigationItems.length}
      statusMessage={
        <div className="space-y-1">
          <p className="text-xs">{statusMessage}</p>
        </div>
      }
      headerActions={
        <div className="flex flex-wrap items-center gap-2">
          {rejected > 0 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={regenerating}
              onClick={() => {
                void handleRegenerate()
              }}
            >
              {regenerating ? 'Regenerating…' : `Regenerate ${rejected} rejected`}
            </Button>
          )}
          {pending > 0 && (
            <Button
              type="button"
              size="sm"
              disabled={approveAllMutation.isPending}
              onClick={() => approveAllMutation.mutate()}
            >
              {approveAllMutation.isPending ? 'Approving…' : 'Approve all'}
            </Button>
          )}
          <ExportDropdown
            workspaceId={workspaceId}
            runId={runId}
            workflowSlug="screenplay"
            variant="outline"
            size="sm"
          />
        </div>
      }
      documentView={
        <FormattingItemList
          items={navigationItems}
          activeIndex={activeIndex}
          onSelect={setActiveIndex}
        />
      }
      inspector={
        activeItem ? (
          <ScreenplayItemInspector
            item={activeItem}
            onApprove={(itemId) => approveMutation.mutate(itemId)}
            onReject={(itemId, comment) => rejectMutation.mutate({ itemId, comment })}
            isApproving={approveMutation.isPending}
            isRejecting={rejectMutation.isPending}
          />
        ) : (
          <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            No item selected.
          </div>
        )
      }
      navigator={
        <ChangeNavigator
          currentIndex={activeIndex}
          total={navigationItems.length}
          onPrevious={() => setActiveIndex((index) => Math.max(0, index - 1))}
          onNext={() =>
            setActiveIndex((index) => Math.min(navigationItems.length - 1, index + 1))
          }
        />
      }
    />
  )
}
