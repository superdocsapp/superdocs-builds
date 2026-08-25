import { useState, useMemo } from 'react'
import { useMutation, useQuery, useQueries, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Folder,
  Play,
  CheckCircle2,
  FileText,
  Plus,
  Search,
  MoreVertical,
  Trash2,
  ChevronLeft,
  ChevronRight,
  SlidersHorizontal,
  Film,
  BookOpen,
} from 'lucide-react'

import { workspaceApi } from '@/core/api/client'
import { runsApi } from '@/core/api/workflowApi'
import type { Workspace } from '@/core/api/types'
import { DocIntelLogo } from '@/features/auth/AuthLayout'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { ErrorState } from '@/shared/components/ErrorState'

import { CreateWorkspaceModal } from './CreateWorkspaceModal'
import { DeleteWorkspaceModal } from './DeleteWorkspaceModal'
import { UserMenu } from '@/core/layout/UserMenu'
import type { WorkflowTypeValue } from './CreateWorkspaceForm'

// Format relative time helper
function formatRelativeTime(dateString: string): string {
  try {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffSecs = Math.floor(diffMs / 1000)
    const diffMins = Math.floor(diffSecs / 60)
    const diffHours = Math.floor(diffMins / 60)
    const diffDays = Math.floor(diffHours / 24)

    if (diffSecs < 60) return 'Just now'
    if (diffMins < 60) return `${diffMins} min${diffMins > 1 ? 's' : ''} ago`
    if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`
    if (diffDays === 1) return 'Yesterday'
    if (diffDays < 7) return `${diffDays} days ago`
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch {
    return 'Recently'
  }
}

// Get workflow display metadata
function getWorkflowMeta(workflowType?: string | null) {
  const type = workflowType?.toLowerCase() || ''
  if (type.includes('tariff')) {
    return {
      label: 'Tariff',
      badgeClass: 'bg-blue-50 text-blue-600',
      iconClass: 'bg-blue-50 text-blue-600 border-blue-100/80',
      Icon: FileText,
      defaultSubtitle: 'Tariff Classification & Compliance',
    }
  }
  if (type.includes('screenplay')) {
    return {
      label: 'Screenplay',
      badgeClass: 'bg-purple-50 text-purple-600',
      iconClass: 'bg-purple-50 text-purple-600 border-purple-100/80',
      Icon: Film,
      defaultSubtitle: 'Screenplay Formatting & Polish',
    }
  }
  if (type.includes('knowledge') || type.includes('ruling')) {
    return {
      label: 'Knowledge',
      badgeClass: 'bg-amber-50 text-amber-700',
      iconClass: 'bg-amber-50 text-amber-600 border-amber-100/80',
      Icon: BookOpen,
      defaultSubtitle: 'Document Knowledge Base',
    }
  }
  return {
    label: workflowType || 'General',
    badgeClass: 'bg-slate-100 text-slate-700',
    iconClass: 'bg-slate-100 text-slate-600 border-slate-200',
    Icon: Folder,
    defaultSubtitle: 'Document Intelligence Project',
  }
}

const ITEMS_PER_PAGE = 6

export function WorkspacesPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Workspace | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // Filters and search
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<'all' | 'tariff' | 'screenplay' | 'knowledge'>('all')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'completed'>('all')
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc')
  const [currentPage, setCurrentPage] = useState(1)

  // Fetch workspaces list
  const {
    data: workspaces,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  // Fetch runs for each workspace to calculate real statistics
  const runQueries = useQueries({
    queries: (workspaces ?? []).map((w) => ({
      queryKey: ['workspaceRuns', w.id],
      queryFn: () => runsApi.list(w.id),
      staleTime: 30_000,
    })),
  })

  // Map runs by workspace ID
  const runsByWorkspace = useMemo(() => {
    const map = new Map<string, any[]>()
    if (!workspaces) return map
    workspaces.forEach((w, index) => {
      const query = runQueries[index]
      map.set(w.id, query?.data || [])
    })
    return map
  }, [workspaces, runQueries])

  // Aggregate summary statistics
  const stats = useMemo(() => {
    const totalWorkspaces = workspaces?.length || 0
    let activeRuns = 0
    let completedRuns = 0
    let exportsGenerated = 0

    runsByWorkspace.forEach((runs) => {
      runs.forEach((r) => {
        if (r.status === 'running' || r.status === 'waiting' || r.status === 'in_progress') {
          activeRuns++
        } else if (r.status === 'completed') {
          completedRuns++
          exportsGenerated++
        }
      })
    })

    return {
      totalWorkspaces,
      activeRuns,
      completedRuns,
      exportsGenerated,
    }
  }, [workspaces, runsByWorkspace])

  // Create Workspace Mutation
  const createMutation = useMutation({
    mutationFn: (data: { name: string; workflowType: WorkflowTypeValue }) =>
      workspaceApi.create({
        name: data.name,
        workflow_type: data.workflowType,
      }),
    onSuccess: (workspace) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      setIsCreateOpen(false)
      navigate(`/workspace/${workspace.id}`)
    },
  })

  // Delete Workspace Mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => workspaceApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      setDeleteTarget(null)
      setDeleteError(null)
    },
    onError: (err: any) => {
      setDeleteError(err.response?.data?.detail || err.message || 'Failed to delete workspace')
    },
  })

  const handleCreate = (name: string, workflowType: WorkflowTypeValue) => {
    createMutation.mutate({ name, workflowType })
  }

  const handleConfirmDelete = () => {
    if (deleteTarget) {
      setDeleteError(null)
      deleteMutation.mutate(deleteTarget.id)
    }
  }

  // Filtered and sorted workspace list
  const filteredWorkspaces = useMemo(() => {
    if (!workspaces) return []

    return workspaces
      .filter((w) => {
        // Search query
        if (searchQuery.trim()) {
          const query = searchQuery.toLowerCase().trim()
          const nameMatch = w.name.toLowerCase().includes(query)
          const typeMatch = (w.workflow_type || '').toLowerCase().includes(query)
          if (!nameMatch && !typeMatch) return false
        }

        // Type filter
        if (typeFilter !== 'all') {
          const wType = (w.workflow_type || '').toLowerCase()
          if (!wType.includes(typeFilter)) return false
        }

        // Status filter
        if (statusFilter !== 'all') {
          const runs = runsByWorkspace.get(w.id) || []
          const hasRunning = runs.some(
            (r) => r.status === 'running' || r.status === 'waiting'
          )
          const computedStatus = hasRunning ? 'active' : (w.status || 'completed').toLowerCase()
          if (statusFilter === 'active' && computedStatus !== 'active') return false
          if (statusFilter === 'completed' && computedStatus !== 'completed') return false
        }

        return true
      })
      .sort((a, b) => {
        const timeA = new Date(a.updated_at || a.created_at).getTime()
        const timeB = new Date(b.updated_at || b.created_at).getTime()
        return sortOrder === 'desc' ? timeB - timeA : timeA - timeB
      })
  }, [workspaces, searchQuery, typeFilter, statusFilter, sortOrder, runsByWorkspace])

  // Pagination calculation
  const totalItems = filteredWorkspaces.length
  const totalPages = Math.max(1, Math.ceil(totalItems / ITEMS_PER_PAGE))
  const paginatedWorkspaces = useMemo(() => {
    const startIndex = (currentPage - 1) * ITEMS_PER_PAGE
    return filteredWorkspaces.slice(startIndex, startIndex + ITEMS_PER_PAGE)
  }, [filteredWorkspaces, currentPage])

  const startItem = totalItems === 0 ? 0 : (currentPage - 1) * ITEMS_PER_PAGE + 1
  const endItem = Math.min(currentPage * ITEMS_PER_PAGE, totalItems)

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] p-6 sm:p-10 lg:p-12">
        <div className="max-w-[1360px] mx-auto space-y-8">
          <div className="flex items-center justify-between">
            <Skeleton className="h-8 w-36" />
            <Skeleton className="h-10 w-40 rounded-lg" />
          </div>
          <div className="space-y-2">
            <Skeleton className="h-10 w-56" />
            <Skeleton className="h-5 w-80" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-28 rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-96 rounded-xl" />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center p-6">
        <ErrorState
          title="Could not load workspaces"
          description="Something went wrong while fetching your workspaces."
          onRetry={() => refetch()}
          error={error}
          className="max-w-lg bg-white rounded-xl shadow-sm border border-slate-200"
        />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 font-sans antialiased selection:bg-blue-100 selection:text-blue-900">
      <div className="max-w-[1360px] mx-auto px-4 sm:px-8 lg:px-12 py-8 sm:py-10">
        {/* Top Navbar */}
        <div className="flex items-center justify-between pb-6">
          <DocIntelLogo />
          <div className="flex items-center gap-5 sm:gap-6">
            <button
              type="button"
              onClick={() => setIsCreateOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-sm font-semibold rounded-lg shadow-sm transition-all duration-150"
            >
              <Plus className="w-4 h-4 stroke-[2.5]" />
              <span>New Workspace</span>
            </button>
            <UserMenu />
          </div>
        </div>

        {/* Page Heading */}
        <div className="mt-4 mb-8">
          <h1 className="text-3xl sm:text-[34px] font-bold text-slate-900 tracking-tight">
            All Workspaces
          </h1>
          <p className="text-sm sm:text-base text-slate-500 mt-1">
            Organize and manage your document intelligence projects.
          </p>
        </div>

        {/* Summary Metric Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-5 mb-8">
          {/* Card 1: Total Workspaces */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 sm:p-6 shadow-[0_1px_3px_rgba(0,0,0,0.03)] flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 border border-blue-100/80 flex items-center justify-center shrink-0">
              <Folder className="w-6 h-6 stroke-[1.75]" />
            </div>
            <div>
              <div className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight leading-none">
                {stats.totalWorkspaces}
              </div>
              <div className="text-xs sm:text-sm font-medium text-slate-500 mt-1.5">
                Total Workspaces
              </div>
            </div>
          </div>

          {/* Card 2: Active Runs */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 sm:p-6 shadow-[0_1px_3px_rgba(0,0,0,0.03)] flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 border border-blue-100/80 flex items-center justify-center shrink-0">
              <Play className="w-6 h-6 stroke-[1.75] fill-blue-50" />
            </div>
            <div>
              <div className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight leading-none">
                {stats.activeRuns}
              </div>
              <div className="text-xs sm:text-sm font-medium text-slate-500 mt-1.5">
                Active Runs
              </div>
            </div>
          </div>

          {/* Card 3: Completed Runs */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 sm:p-6 shadow-[0_1px_3px_rgba(0,0,0,0.03)] flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-emerald-50 text-emerald-600 border border-emerald-100/80 flex items-center justify-center shrink-0">
              <CheckCircle2 className="w-6 h-6 stroke-[1.75]" />
            </div>
            <div>
              <div className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight leading-none">
                {stats.completedRuns}
              </div>
              <div className="text-xs sm:text-sm font-medium text-slate-500 mt-1.5">
                Completed Runs
              </div>
            </div>
          </div>

          {/* Card 4: Exports Generated */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 sm:p-6 shadow-[0_1px_3px_rgba(0,0,0,0.03)] flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-slate-100 text-slate-600 border border-slate-200 flex items-center justify-center shrink-0">
              <FileText className="w-6 h-6 stroke-[1.75]" />
            </div>
            <div>
              <div className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight leading-none">
                {stats.exportsGenerated}
              </div>
              <div className="text-xs sm:text-sm font-medium text-slate-500 mt-1.5">
                Exports Generated
              </div>
            </div>
          </div>
        </div>

        {/* Main Workspaces Table Card */}
        <div className="bg-white border border-slate-200/90 rounded-2xl shadow-[0_1px_3px_rgba(0,0,0,0.03)] overflow-hidden">
          {/* Filter Bar */}
          <div className="p-4 sm:p-5 border-b border-slate-100 flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 sm:gap-4">
            {/* Search Input */}
            <div className="relative flex-1 max-w-md">
              <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                placeholder="Search workspaces..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value)
                  setCurrentPage(1)
                }}
                className="w-full pl-10 pr-4 py-2 text-sm bg-white border border-slate-200 rounded-lg placeholder:text-slate-400 text-slate-900 focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-600 transition-colors"
              />
            </div>

            {/* Filter Controls */}
            <div className="flex items-center gap-2.5 flex-wrap">
              {/* Type Filter */}
              <select
                aria-label="Filter by workflow type"
                value={typeFilter}
                onChange={(e) => {
                  setTypeFilter(e.target.value as any)
                  setCurrentPage(1)
                }}
                className="px-3.5 py-2 text-xs sm:text-sm font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:border-slate-300 focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-600 cursor-pointer"
              >
                <option value="all">All Types</option>
                <option value="tariff">Tariff</option>
                <option value="screenplay">Screenplay</option>
                <option value="knowledge">Knowledge</option>
              </select>

              {/* Status Filter */}
              <select
                aria-label="Filter by status"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value as any)
                  setCurrentPage(1)
                }}
                className="px-3.5 py-2 text-xs sm:text-sm font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:border-slate-300 focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-600 cursor-pointer"
              >
                <option value="all">All Statuses</option>
                <option value="active">Active</option>
                <option value="completed">Completed</option>
              </select>

              {/* Sorting Button */}
              <button
                type="button"
                onClick={() => setSortOrder(sortOrder === 'desc' ? 'asc' : 'desc')}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs sm:text-sm font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
              >
                <span>Last Updated</span>
                <SlidersHorizontal className="w-3.5 h-3.5 text-slate-500" />
              </button>
            </div>
          </div>

          {/* Table Container */}
          {paginatedWorkspaces.length === 0 ? (
            <div className="py-16 px-6 text-center">
              <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-3">
                <Folder className="w-6 h-6" />
              </div>
              <h3 className="text-base font-semibold text-slate-900">No workspaces found</h3>
              <p className="text-sm text-slate-500 mt-1 max-w-sm mx-auto">
                {searchQuery || typeFilter !== 'all' || statusFilter !== 'all'
                  ? 'No workspaces match your current search and filter criteria.'
                  : 'Get started by creating your first document intelligence workspace.'}
              </p>
              {!searchQuery && typeFilter === 'all' && statusFilter === 'all' && (
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(true)}
                  className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  <span>Create Workspace</span>
                </button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/40 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    <th className="py-3.5 px-6 font-semibold">Workspace</th>
                    <th className="py-3.5 px-6 font-semibold">Type</th>
                    <th className="py-3.5 px-6 font-semibold">Status</th>
                    <th className="py-3.5 px-6 font-semibold">Runs</th>
                    <th className="py-3.5 px-6 font-semibold">Last Updated</th>
                    <th className="py-3.5 px-6 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {paginatedWorkspaces.map((workspace) => {
                    const meta = getWorkflowMeta(workspace.workflow_type)
                    const IconComponent = meta.Icon
                    const runs = runsByWorkspace.get(workspace.id) || []
                    const totalRuns = runs.length
                    const runningCount = runs.filter(
                      (r) => r.status === 'running' || r.status === 'waiting'
                    ).length
                    const isWorkspaceActive = runningCount > 0 || (workspace.status || '').toLowerCase() === 'active'

                    return (
                      <tr
                        key={workspace.id}
                        onClick={() => navigate(`/workspace/${workspace.id}`)}
                        className="hover:bg-slate-50/70 transition-colors cursor-pointer group"
                      >
                        {/* Workspace Name & Subtitle */}
                        <td className="py-4 px-6">
                          <div className="flex items-center gap-3.5">
                            <div
                              className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border ${meta.iconClass}`}
                            >
                              <IconComponent className="w-5 h-5 stroke-[1.75]" />
                            </div>
                            <div>
                              <div className="text-sm font-semibold text-slate-900 group-hover:text-blue-600 transition-colors">
                                {workspace.name}
                              </div>
                              <div className="text-xs text-slate-500 mt-0.5">
                                {meta.defaultSubtitle}
                              </div>
                            </div>
                          </div>
                        </td>

                        {/* Type Badge */}
                        <td className="py-4 px-6">
                          <span
                            className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium ${meta.badgeClass}`}
                          >
                            {meta.label}
                          </span>
                        </td>

                        {/* Status Badge */}
                        <td className="py-4 px-6">
                          {isWorkspaceActive ? (
                            <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-emerald-50 text-emerald-700">
                              Active
                            </span>
                          ) : (
                            <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-slate-100 text-slate-600">
                              Completed
                            </span>
                          )}
                        </td>

                        {/* Runs Count */}
                        <td className="py-4 px-6">
                          <div className="text-sm font-medium text-slate-900">
                            {totalRuns > 0 ? totalRuns : '0'}
                          </div>
                          <div className="text-xs text-slate-400 mt-0.5">
                            {runningCount > 0 ? `${runningCount} running` : totalRuns > 0 ? '0 running' : '—'}
                          </div>
                        </td>

                        {/* Last Updated */}
                        <td className="py-4 px-6 text-sm text-slate-500">
                          {formatRelativeTime(workspace.updated_at || workspace.created_at)}
                        </td>

                        {/* Actions Menu (Contains ONLY Delete) */}
                        <td
                          className="py-4 px-6 text-right"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button
                                type="button"
                                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 focus:outline-none transition-colors"
                                aria-label="Workspace actions"
                              >
                                <MoreVertical className="w-4 h-4" />
                              </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-36 bg-white border border-slate-200 shadow-md rounded-lg p-1">
                              <DropdownMenuItem
                                onClick={() => {
                                  setDeleteError(null)
                                  setDeleteTarget(workspace)
                                }}
                                className="flex items-center gap-2 px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 focus:bg-red-50 focus:text-red-600 rounded cursor-pointer transition-colors"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                                <span>Delete</span>
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination Footer */}
          {totalItems > 0 && (
            <div className="p-4 sm:p-5 border-t border-slate-100 flex items-center justify-between flex-wrap gap-3">
              <div className="text-xs sm:text-sm text-slate-500">
                Showing {startItem} to {endItem} of {totalItems} workspaces
              </div>

              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className="p-1.5 rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  aria-label="Previous page"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>

                {Array.from({ length: totalPages }).map((_, idx) => {
                  const pageNum = idx + 1
                  const isActive = currentPage === pageNum
                  return (
                    <button
                      key={pageNum}
                      type="button"
                      onClick={() => setCurrentPage(pageNum)}
                      className={`min-w-[32px] h-8 px-2 text-xs font-semibold rounded-md transition-colors ${
                        isActive
                          ? 'bg-blue-600 text-white'
                          : 'border border-slate-200 text-slate-700 hover:bg-slate-50'
                      }`}
                    >
                      {pageNum}
                    </button>
                  )
                })}

                <button
                  type="button"
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages}
                  className="p-1.5 rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  aria-label="Next page"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Create Workspace Modal */}
      <CreateWorkspaceModal
        open={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onCreate={handleCreate}
        isSubmitting={createMutation.isPending}
      />

      {/* Custom Delete Confirmation Modal */}
      <DeleteWorkspaceModal
        open={deleteTarget !== null}
        workspaceName={deleteTarget?.name}
        isDeleting={deleteMutation.isPending}
        error={deleteError}
        onClose={() => {
          setDeleteTarget(null)
          setDeleteError(null)
        }}
        onConfirm={handleConfirmDelete}
      />
    </div>
  )
}

