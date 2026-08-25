import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { BookOpen, Search, X, Filter } from 'lucide-react'

import { workspaceApi } from '@/core/api/client'
import { knowledgeApi, type KnowledgeEntry } from '@/core/api/knowledgeApi'
import { useAuth } from '@/core/auth/AuthContext'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { ErrorState } from '@/shared/components/ErrorState'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { cn } from '@/lib/utils'

import { KnowledgeCard } from './KnowledgeCard'
import { KnowledgeDetailDrawer } from './KnowledgeDetailDrawer'

const FILTER_TABS = [
  { id: 'all', label: 'All entries' },
  { id: 'claim', label: 'Claims' },
  { id: 'summary', label: 'Summaries' },
  { id: 'full_output', label: 'Full outputs' },
]

function matchesSearch(entry: KnowledgeEntry, query: string): boolean {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return true

  const haystack = [entry.content, ...entry.tags].join(' ').toLowerCase()
  return haystack.includes(normalized)
}

export function KnowledgePage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const { accessToken } = useAuth()
  const queryClient = useQueryClient()

  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [selectedEntry, setSelectedEntry] = useState<KnowledgeEntry | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeEntry | null>(null)

  const workspaceQuery = useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => workspaceApi.get(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const workflowType = workspaceQuery.data?.workflow_type || 'tariff_classification'

  const knowledgeQuery = useQuery({
    queryKey: ['knowledge', workspaceId, workflowType],
    queryFn: () => knowledgeApi.listByWorkspace(workspaceId!, { workflow_type: workflowType }),
    enabled: !!workspaceId && !!accessToken && workspaceQuery.isSuccess,
  })

  const deleteMutation = useMutation({
    mutationFn: (entryId: string) => knowledgeApi.delete(workspaceId!, entryId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge', workspaceId] })
      setDeleteTarget(null)
      setDrawerOpen(false)
      setSelectedEntry(null)
    },
  })

  const allEntries = knowledgeQuery.data ?? []

  const counts = useMemo(() => {
    return {
      all: allEntries.length,
      claim: allEntries.filter((e) => e.entry_type === 'claim').length,
      summary: allEntries.filter((e) => e.entry_type === 'summary').length,
      full_output: allEntries.filter((e) => e.entry_type === 'full_output').length,
    }
  }, [allEntries])

  const filteredEntries = useMemo(() => {
    return allEntries
      .filter((entry) => typeFilter === 'all' || entry.entry_type === typeFilter)
      .filter((entry) => matchesSearch(entry, search))
      .sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      )
  }, [allEntries, search, typeFilter])

  const handleOpenEntry = (entry: KnowledgeEntry) => {
    setSelectedEntry(entry)
    setDrawerOpen(true)
  }

  const handleDeleteRequest = (entry: KnowledgeEntry) => {
    setDeleteTarget(entry)
  }

  const handleConfirmDelete = () => {
    if (deleteTarget) {
      deleteMutation.mutate(deleteTarget.id)
    }
  }

  if (!workspaceId) {
    return null
  }

  const isLoading = workspaceQuery.isLoading || knowledgeQuery.isLoading
  const error = workspaceQuery.error ?? knowledgeQuery.error

  return (
    <div className="space-y-6">
      {/* 1. Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
            Knowledge Base
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Reusable classifications, rules, and insights extracted from completed workflows.
          </p>
        </div>
      </div>

      {/* 2. Filter Pills & Search */}
      <div className="space-y-3">
        {/* Filter Pills */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 no-scrollbar">
          {FILTER_TABS.map((tab) => {
            const isActive = typeFilter === tab.id
            const count = counts[tab.id as keyof typeof counts] ?? 0
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setTypeFilter(tab.id)}
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
            placeholder="Search knowledge content, product, or tags…"
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

      {/* 3. Knowledge Cards Grid */}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={index}
              className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs space-y-3"
            >
              <div className="flex justify-between items-center">
                <Skeleton className="h-5 w-20 rounded-md" />
                <Skeleton className="h-4 w-16" />
              </div>
              <Skeleton className="h-12 w-full rounded-xl" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-9 w-full rounded-xl" />
            </div>
          ))}
        </div>
      ) : error ? (
        <ErrorState
          title="Could not load knowledge"
          description="Something went wrong while fetching knowledge entries."
          onRetry={() => {
            void workspaceQuery.refetch()
            void knowledgeQuery.refetch()
          }}
          error={error}
        />
      ) : allEntries.length === 0 ? (
        <div className="bg-white border border-slate-200/90 rounded-2xl p-12 text-center shadow-sm">
          <div className="w-12 h-12 rounded-2xl bg-emerald-50 text-emerald-600 border border-emerald-100 flex items-center justify-center mx-auto mb-3">
            <BookOpen className="w-6 h-6 stroke-[1.75]" />
          </div>
          <h3 className="text-base font-bold text-slate-900 tracking-tight">
            No knowledge entries yet
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
            Knowledge is generated as workflows complete and can be reused in future runs.
          </p>
        </div>
      ) : filteredEntries.length === 0 ? (
        <div className="bg-white border border-slate-200/90 rounded-2xl p-10 text-center shadow-sm">
          <div className="w-10 h-10 rounded-xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-2.5">
            <Filter className="w-5 h-5" />
          </div>
          <h3 className="text-sm font-bold text-slate-900">No matching entries</h3>
          <p className="text-xs text-slate-500 mt-0.5 mb-4">
            No knowledge entries match your active filter and search criteria.
          </p>
          <button
            type="button"
            onClick={() => {
              setSearch('')
              setTypeFilter('all')
            }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors cursor-pointer"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredEntries.map((entry) => (
            <KnowledgeCard key={entry.id} entry={entry} onOpen={handleOpenEntry} />
          ))}
        </div>
      )}

      {/* Drawer */}
      <KnowledgeDetailDrawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        entry={selectedEntry}
        workspaceId={workspaceId}
        onDelete={handleDeleteRequest}
      />

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete knowledge entry"
        description={
          deleteTarget
            ? 'Are you sure you want to delete this knowledge entry? This action cannot be undone.'
            : 'Are you sure you want to delete this knowledge entry?'
        }
        confirmLabel="Delete"
        destructive
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}

