import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ClipboardCheck,
  Search,
  X,
  Users,
  Clock,
  Filter,
  ArrowUpRight,
} from 'lucide-react'

import { reviewApi } from '@/core/api/reviewApi'
import { workspaceApi } from '@/core/api/client'
import { useAuth } from '@/core/auth/AuthContext'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { ErrorState } from '@/shared/components/ErrorState'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { formatRelativeTime } from '@/shared/utils/formatDate'
import { cn } from '@/lib/utils'

interface ReviewListItem {
  id: string
  workflow_run_id?: string | null
  status: string
  notes?: string | null
  created_at: string
  isScreenplayRun?: boolean
}

type FilterTab = 'all' | 'pending' | 'approved' | 'rejected'

const FILTER_TABS: Array<{ id: FilterTab; label: string }> = [
  { id: 'all', label: 'All reviews' },
  { id: 'pending', label: 'Requires review' },
  { id: 'approved', label: 'Approved' },
  { id: 'rejected', label: 'Rejected' },
]

function matchesStatus(status: string, filter: FilterTab): boolean {
  if (filter === 'all') return true
  const s = status.toLowerCase()
  if (filter === 'pending') {
    return ['in_review', 'pending', 'awaiting_review', 'waiting'].includes(s)
  }
  if (filter === 'approved') {
    return s === 'approved' || s === 'accepted'
  }
  if (filter === 'rejected') {
    return s === 'rejected' || s === 'declined'
  }
  return true
}

export function ReviewsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const { accessToken } = useAuth()
  const basePath = `/workspace/${workspaceId}`

  const [filterTab, setFilterTab] = useState<FilterTab>('all')
  const [search, setSearch] = useState('')

  const workspaceQuery = useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => workspaceApi.get(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const isScreenplay = workspaceQuery.data?.workflow_type === 'screenplay'

  const reviewsQuery = useQuery({
    queryKey: ['reviews', workspaceId],
    queryFn: () => reviewApi.listWorkspaceReviews(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const allReviews: ReviewListItem[] = useMemo(() => {
    const rawReviews = reviewsQuery.data ?? []
    return rawReviews.map((r) => ({
      id: r.id,
      workflow_run_id: r.workflow_run_id,
      status: r.status,
      notes:
        r.notes ||
        (isScreenplay
          ? `Screenplay formatting review for run ${r.workflow_run_id?.slice(0, 8)}. Inspect elements, approve corrections, or regenerate.`
          : undefined),
      created_at: r.created_at,
      isScreenplayRun: isScreenplay,
    }))
  }, [isScreenplay, reviewsQuery.data])

  const counts = useMemo(() => {
    return {
      all: allReviews.length,
      pending: allReviews.filter((r) =>
        ['in_review', 'pending', 'awaiting_review', 'waiting'].includes(r.status.toLowerCase())
      ).length,
      approved: allReviews.filter((r) =>
        ['approved', 'accepted'].includes(r.status.toLowerCase())
      ).length,
      rejected: allReviews.filter((r) =>
        ['rejected', 'declined'].includes(r.status.toLowerCase())
      ).length,
    }
  }, [allReviews])

  const filteredReviews = useMemo(() => {
    let result = allReviews.filter((r) => matchesStatus(r.status, filterTab))

    if (search.trim()) {
      const query = search.trim().toLowerCase()
      result = result.filter((r) => {
        const idMatch = r.id.toLowerCase().includes(query)
        const notesMatch = r.notes ? r.notes.toLowerCase().includes(query) : false
        const runIdMatch = r.workflow_run_id ? r.workflow_run_id.toLowerCase().includes(query) : false
        return idMatch || notesMatch || runIdMatch
      })
    }

    return result.sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
  }, [allReviews, filterTab, search])

  if (reviewsQuery.isError) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">Reviews</h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Human review queue for workflow proposals and changes.
          </p>
        </div>
        <ErrorState
          title="Couldn't load reviews"
          description="We couldn't fetch reviews for this workspace."
          onRetry={() => void reviewsQuery.refetch()}
          error={reviewsQuery.error}
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* 1. Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">Reviews</h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Human-in-the-loop review queue for workflow proposals and changes.
          </p>
        </div>
      </div>

      {/* 2. Filter Pills & Search */}
      <div className="space-y-3">
        {/* Pills */}
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

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
          <input
            type="text"
            placeholder="Search by review ID, notes, or run ID…"
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

      {/* 3. Review Cards List */}
      {reviewsQuery.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs flex items-center justify-between gap-4"
            >
              <div className="flex items-center gap-3.5 min-w-0 flex-1">
                <Skeleton className="w-10 h-10 rounded-xl" />
                <div className="space-y-2 min-w-0 flex-1">
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-3 w-72" />
                </div>
              </div>
              <Skeleton className="h-9 w-28 rounded-lg" />
            </div>
          ))}
        </div>
      ) : allReviews.length === 0 ? (
        <div className="bg-white border border-slate-200/90 rounded-2xl p-12 text-center shadow-sm">
          <div className="w-12 h-12 rounded-2xl bg-amber-50 text-amber-600 border border-amber-100 flex items-center justify-center mx-auto mb-3">
            <ClipboardCheck className="w-6 h-6 stroke-[1.75]" />
          </div>
          <h3 className="text-base font-bold text-slate-900 tracking-tight">No reviews yet</h3>
          <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
            Reviews appear here when a workflow needs human input or manual verification.
          </p>
        </div>
      ) : filteredReviews.length === 0 ? (
        <div className="bg-white border border-slate-200/90 rounded-2xl p-10 text-center shadow-sm">
          <div className="w-10 h-10 rounded-xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-2.5">
            <Filter className="w-5 h-5" />
          </div>
          <h3 className="text-sm font-bold text-slate-900">No matching reviews</h3>
          <p className="text-xs text-slate-500 mt-0.5 mb-4">
            No reviews match your active filter and search criteria.
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
          {filteredReviews.map((review) => {
            const isPending = ['in_review', 'pending', 'awaiting_review', 'waiting'].includes(
              review.status.toLowerCase()
            )

            return (
              <div
                key={review.id}
                className={cn(
                  'bg-white border rounded-2xl p-5 shadow-xs transition-all duration-150 flex flex-col md:flex-row md:items-center justify-between gap-4 group',
                  isPending
                    ? 'border-amber-300 ring-1 ring-amber-300/30'
                    : 'border-slate-200/90 hover:border-slate-300'
                )}
              >
                {/* Left / Info */}
                <div className="flex items-start gap-3.5 min-w-0 flex-1">
                  <div
                    className={cn(
                      'w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border mt-0.5',
                      isPending
                        ? 'bg-amber-50 text-amber-600 border-amber-100'
                        : 'bg-slate-50 text-slate-600 border-slate-100'
                    )}
                  >
                    <Users className="w-4 h-4 stroke-[2]" />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        to={
                          review.isScreenplayRun
                            ? `${basePath}/runs/${review.workflow_run_id}/review`
                            : `${basePath}/reviews/${review.id}`
                        }
                        className="text-sm font-bold text-slate-900 hover:text-blue-600 transition-colors tracking-tight"
                      >
                        {review.isScreenplayRun ? 'Screenplay Formatting Review' : 'SuperDocs Review'}
                      </Link>
                      <StatusBadge status={review.status} type="review" />
                    </div>

                    <p className="text-xs text-slate-600 mt-1 leading-relaxed">
                      {review.notes || 'Review and approve changes for the generated document.'}
                    </p>

                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400 mt-2.5">
                      <span className="font-mono text-[11px] text-slate-500">
                        ID: {review.id.slice(0, 8)}…{review.id.slice(-4)}
                      </span>

                      {review.workflow_run_id && (
                        <span className="font-mono text-[11px] text-slate-400">
                          Run: {review.workflow_run_id.slice(0, 8)}…
                        </span>
                      )}

                      <div className="flex items-center gap-1 text-[11px]">
                        <Clock className="w-3 h-3 text-slate-400" />
                        <span>{formatRelativeTime(review.created_at)}</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Right Action */}
                <div className="flex items-center gap-2 shrink-0 self-end md:self-center">
                  <Link
                    to={
                      review.isScreenplayRun
                        ? `${basePath}/runs/${review.workflow_run_id}/review`
                        : `${basePath}/reviews/${review.id}`
                    }
                    className={cn(
                      'inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg shadow-xs transition-colors cursor-pointer',
                      isPending
                        ? 'bg-amber-500 hover:bg-amber-600 text-white'
                        : 'bg-slate-100 hover:bg-slate-200 text-slate-800'
                    )}
                  >
                    <span>{isPending ? 'Review changes' : 'View review'}</span>
                    <ArrowUpRight className="w-3.5 h-3.5 opacity-80" />
                  </Link>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

