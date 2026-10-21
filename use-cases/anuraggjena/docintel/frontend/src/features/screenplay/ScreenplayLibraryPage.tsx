import { useState, useRef, useMemo } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Film,
  UploadCloud,
  Search,
  LayoutGrid,
  List as ListIcon,
  Clock,
  ArrowUpRight,
  Sparkles,
  Layers,
  FileText,
  CheckCircle2,
  AlertCircle,
  Loader2,
  RefreshCw,
} from 'lucide-react'

import { screenplayApi } from '@/core/api/screenplayApi'
import { documentApi } from '@/core/api/documentApi'
import { runsApi } from '@/core/api/workflowApi'
import { useAuth } from '@/core/auth/AuthContext'
import { formatRelativeTime, formatDate } from '@/shared/utils/formatDate'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { ErrorState } from '@/shared/components/ErrorState'
import { cn } from '@/lib/utils'

export function ScreenplayLibraryPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const { user, accessToken } = useAuth()
  const navigate = useNavigate()

  const [searchQuery, setSearchQuery] = useState('')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Fetch screenplay library items (scoped strictly to screenplay workspaces/documents)
  const libraryQuery = useQuery({
    queryKey: ['screenplay-library'],
    queryFn: () => screenplayApi.getLibrary(),
    enabled: !!accessToken,
  })

  const libraryItems = libraryQuery.data ?? []

  // Filter items by search query
  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) return libraryItems
    const q = searchQuery.toLowerCase().trim()
    return libraryItems.filter(
      (item) =>
        item.filename.toLowerCase().includes(q) ||
        item.workspace_name.toLowerCase().includes(q) ||
        (item.run_status && item.run_status.toLowerCase().includes(q))
    )
  }, [libraryItems, searchQuery])

  // Aggregate metrics
  const stats = useMemo(() => {
    const total = libraryItems.length
    const readyForReview = libraryItems.filter(
      (it) => (it.pending_items_count && it.pending_items_count > 0) || it.run_status === 'waiting'
    ).length
    const completed = libraryItems.filter(
      (it) => it.run_status === 'completed' && (!it.pending_items_count || it.pending_items_count === 0)
    ).length
    return { total, readyForReview, completed }
  }, [libraryItems])

  // Handle screenplay file upload
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !workspaceId) return

    try {
      setIsUploading(true)
      setUploadError(null)

      // 1. Upload the screenplay document
      const doc = await documentApi.upload(workspaceId, file, 'product_spec')

      // 2. Start the screenplay formatting workflow run
      const run = await runsApi.create(workspaceId, {
        workflow_slug: 'screenplay',
        document_id: doc.id,
        created_by: user?.email || 'user',
      })

      // Refetch library
      void libraryQuery.refetch()

      // 3. Navigate to the screenplay run workspace
      navigate(`/workspace/${workspaceId}/runs/${run.id}`)
    } catch (err: unknown) {
      const errorMsg =
        err instanceof Error ? err.message : 'Failed to upload and process screenplay script.'
      setUploadError(errorMsg)
      setIsUploading(false)
    }
  }

  const triggerUpload = () => {
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
      fileInputRef.current.click()
    }
  }

  // Format clean script title
  const formatTitle = (filename: string) => {
    return filename.replace(/\.[^/.]+$/, '').replace(/[-_]/g, ' ')
  }

  // Get file extension badge
  const getFileExtension = (filename: string) => {
    const parts = filename.split('.')
    return parts.length > 1 ? parts.pop()?.toUpperCase() : 'DOC'
  }

  return (
    <div className="space-y-6 max-w-[1400px] mx-auto pb-12">
      {/* Hidden File Input for Screenplay Upload */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.pdf,.docx,.doc"
        className="hidden"
        onChange={(e) => void handleFileSelect(e)}
      />

      {/* 1. Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600 shadow-2xs">
              <Film className="w-4 h-4" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">My Screenplays</h1>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            All screenplay scripts and formatted documents uploaded for processing, scene extraction, and analysis.
          </p>
        </div>

        {/* Header Actions */}
        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={() => void libraryQuery.refetch()}
            disabled={libraryQuery.isFetching}
            className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors cursor-pointer"
            title="Refresh library"
          >
            <RefreshCw className={cn('w-4 h-4', libraryQuery.isFetching && 'animate-spin text-blue-600')} />
          </button>

          <button
            onClick={triggerUpload}
            disabled={isUploading}
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg shadow-xs transition-colors cursor-pointer disabled:opacity-50"
          >
            {isUploading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Uploading…</span>
              </>
            ) : (
              <>
                <UploadCloud className="w-4 h-4" />
                <span>Upload screenplay</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Upload Error Banner if any */}
      {uploadError && (
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
          <div className="text-xs text-rose-800">
            <span className="font-semibold">Upload failed:</span> {uploadError}
          </div>
        </div>
      )}

      {/* 2. Stat Summary Bar (when populated) */}
      {!libraryQuery.isLoading && libraryItems.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-white border border-slate-200/90 rounded-xl p-4 shadow-2xs flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center text-slate-700 shrink-0">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-900 leading-none">{stats.total}</div>
              <div className="text-xs font-medium text-slate-500 mt-1">Total Screenplays</div>
            </div>
          </div>

          <div className="bg-white border border-slate-200/90 rounded-xl p-4 shadow-2xs flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-50 border border-amber-100 flex items-center justify-center text-amber-600 shrink-0">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <div className="text-2xl font-bold text-amber-900 leading-none">{stats.readyForReview}</div>
              <div className="text-xs font-medium text-slate-500 mt-1">Pending Review</div>
            </div>
          </div>

          <div className="bg-white border border-slate-200/90 rounded-xl p-4 shadow-2xs flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center text-emerald-600 shrink-0">
              <CheckCircle2 className="w-3 h-3 text-emerald-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-emerald-900 leading-none">{stats.completed}</div>
              <div className="text-xs font-medium text-slate-500 mt-1">Formatted & Ready</div>
            </div>
          </div>
        </div>
      )}

      {/* 3. Search and View Controls */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-white border border-slate-200 rounded-xl p-2.5 shadow-2xs">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search screenplay scripts by title, file name, or workspace..."
            className="w-full pl-9 pr-3 py-1.5 text-xs text-slate-800 placeholder-slate-400 bg-slate-50 hover:bg-slate-100/70 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500 border border-slate-200 rounded-lg transition-colors"
          />
        </div>

        {/* View Switcher */}
        <div className="flex items-center gap-1 self-end sm:self-center bg-slate-100 p-1 rounded-lg border border-slate-200">
          <button
            onClick={() => setViewMode('grid')}
            className={cn(
              'p-1.5 rounded-md text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5',
              viewMode === 'grid'
                ? 'bg-white text-slate-900 shadow-2xs font-semibold'
                : 'text-slate-500 hover:text-slate-900'
            )}
            title="Grid view"
          >
            <LayoutGrid className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Grid</span>
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={cn(
              'p-1.5 rounded-md text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5',
              viewMode === 'list'
                ? 'bg-white text-slate-900 shadow-2xs font-semibold'
                : 'text-slate-500 hover:text-slate-900'
            )}
            title="List view"
          >
            <ListIcon className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">List</span>
          </button>
        </div>
      </div>

      {/* 4. Loading State */}
      {libraryQuery.isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((idx) => (
            <div key={idx} className="bg-white border border-slate-200 rounded-xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <Skeleton className="h-6 w-16 rounded" />
                <Skeleton className="h-5 w-20 rounded-full" />
              </div>
              <Skeleton className="h-6 w-3/4 rounded" />
              <div className="space-y-2">
                <Skeleton className="h-4 w-1/2 rounded" />
                <Skeleton className="h-4 w-2/3 rounded" />
              </div>
              <Skeleton className="h-9 w-full rounded-lg" />
            </div>
          ))}
        </div>
      )}

      {/* 5. Error State */}
      {libraryQuery.isError && (
        <ErrorState
          title="Could not load screenplays"
          description="There was a problem retrieving your screenplay library. Please try again."
          onRetry={() => void libraryQuery.refetch()}
          error={libraryQuery.error}
        />
      )}

      {/* 6. Empty State */}
      {!libraryQuery.isLoading && !libraryQuery.isError && libraryItems.length === 0 && (
        <div className="bg-white border-2 border-dashed border-slate-200 rounded-2xl p-12 text-center max-w-xl mx-auto my-8">
          <div className="w-16 h-16 rounded-2xl bg-blue-50 border border-blue-200/70 flex items-center justify-center text-blue-600 mx-auto shadow-xs">
            <Film className="w-8 h-8" />
          </div>
          <h2 className="text-xl font-bold text-slate-900 mt-5">No screenplays yet</h2>
          <p className="text-sm text-slate-500 mt-2 max-w-md mx-auto leading-relaxed">
            Upload a screenplay script (.txt, .pdf, or .docx) to start formatting, scene parsing, and industry-standard analysis.
          </p>
          <div className="mt-6 flex flex-col sm:flex-row items-center justify-center gap-3">
            <button
              onClick={triggerUpload}
              disabled={isUploading}
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-xl shadow-xs transition-colors cursor-pointer"
            >
              <UploadCloud className="w-4 h-4" />
              <span>Upload screenplay</span>
            </button>
          </div>
        </div>
      )}

      {/* 7. No Search Results */}
      {!libraryQuery.isLoading && !libraryQuery.isError && libraryItems.length > 0 && filteredItems.length === 0 && (
        <div className="bg-white border border-slate-200 rounded-2xl p-10 text-center max-w-md mx-auto">
          <Search className="w-8 h-8 text-slate-400 mx-auto mb-2" />
          <h3 className="text-base font-semibold text-slate-900">No screenplays found</h3>
          <p className="text-xs text-slate-500 mt-1">
            No scripts matched &ldquo;{searchQuery}&rdquo;. Try clearing your search term.
          </p>
          <button
            onClick={() => setSearchQuery('')}
            className="mt-4 px-3 py-1.5 text-xs font-semibold text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-lg border border-blue-200 transition-colors cursor-pointer"
          >
            Clear search
          </button>
        </div>
      )}

      {/* 8. Populated Screenplay Grid */}
      {!libraryQuery.isLoading && !libraryQuery.isError && filteredItems.length > 0 && viewMode === 'grid' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredItems.map((item) => {
            const hasPending = (item.pending_items_count && item.pending_items_count > 0) || item.run_status === 'waiting'
            const isCompleted = item.run_status === 'completed' && !hasPending
            const targetRunPath = item.run_id
              ? `/workspace/${item.workspace_id}/runs/${item.run_id}`
              : `/workspace/${item.workspace_id}`
            const reviewPath = item.run_id
              ? `/workspace/${item.workspace_id}/runs/${item.run_id}/review`
              : targetRunPath

            return (
              <div
                key={item.id}
                className={cn(
                  'bg-white border rounded-2xl p-5 shadow-2xs hover:shadow-md transition-all duration-200 flex flex-col justify-between group',
                  hasPending ? 'border-amber-200 ring-1 ring-amber-100' : 'border-slate-200/90 hover:border-slate-300'
                )}
              >
                <div>
                  {/* Top: File Extension Badge & Status Pill */}
                  <div className="flex items-center justify-between gap-2 mb-3.5">
                    <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-mono font-bold bg-slate-100 text-slate-700 border border-slate-200">
                      .{getFileExtension(item.filename)}
                    </span>

                    {hasPending ? (
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                        Ready for review
                      </span>
                    ) : isCompleted ? (
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                        <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                        Formatted
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
                        {item.processing_status || 'Draft'}
                      </span>
                    )}
                  </div>

                  {/* Title */}
                  <Link
                    to={targetRunPath}
                    className="text-base font-bold text-slate-900 group-hover:text-blue-600 transition-colors line-clamp-1 capitalize tracking-tight"
                    title={item.filename}
                  >
                    {formatTitle(item.filename)}
                  </Link>

                  <p className="text-xs text-slate-400 font-mono mt-0.5 truncate" title={item.filename}>
                    {item.filename}
                  </p>

                  {/* Metadata Info */}
                  <div className="mt-4 pt-3.5 border-t border-slate-100 space-y-2 text-xs text-slate-500">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-slate-400">
                        <Layers className="w-3.5 h-3.5" />
                        Scenes parsed:
                      </span>
                      <span className="font-semibold text-slate-700">
                        {item.scenes_count ? `${item.scenes_count} scenes` : '—'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-slate-400">
                        <Clock className="w-3.5 h-3.5" />
                        Uploaded:
                      </span>
                      <span className="text-slate-600" title={formatDate(item.created_at)}>
                        {formatRelativeTime(item.created_at)}
                      </span>
                    </div>

                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-slate-400">
                        <Film className="w-3.5 h-3.5" />
                        Workspace:
                      </span>
                      <span className="text-slate-700 font-medium truncate max-w-[150px]" title={item.workspace_name}>
                        {item.workspace_name}
                      </span>
                    </div>

                    {item.pending_items_count !== undefined && item.pending_items_count !== null && item.pending_items_count > 0 && (
                      <div className="flex items-center justify-between text-amber-700 font-medium">
                        <span className="flex items-center gap-1.5 text-amber-600">
                          <Sparkles className="w-3.5 h-3.5" />
                          Pending changes:
                        </span>
                        <span>{item.pending_items_count} items</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Bottom Actions */}
                <div className="mt-5 pt-3.5 border-t border-slate-100 flex items-center justify-between gap-2">
                  <Link
                    to={targetRunPath}
                    className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-semibold rounded-lg transition-colors"
                  >
                    <span>Open workspace</span>
                    <ArrowUpRight className="w-3.5 h-3.5 text-slate-500" />
                  </Link>

                  {hasPending && (
                    <Link
                      to={reviewPath}
                      className="inline-flex items-center justify-center gap-1.5 px-3 py-2 bg-amber-500 hover:bg-amber-600 text-white text-xs font-semibold rounded-lg shadow-2xs transition-colors"
                      title="Review changes"
                    >
                      <span>Review</span>
                    </Link>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* 9. Populated Screenplay List View */}
      {!libraryQuery.isLoading && !libraryQuery.isError && filteredItems.length > 0 && viewMode === 'list' && (
        <div className="bg-white border border-slate-200/90 rounded-2xl shadow-2xs overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-semibold uppercase tracking-wider text-[10px]">
                <tr>
                  <th className="py-3.5 px-5">Screenplay Document</th>
                  <th className="py-3.5 px-4">Status</th>
                  <th className="py-3.5 px-4">Scenes</th>
                  <th className="py-3.5 px-4">Workspace</th>
                  <th className="py-3.5 px-4">Uploaded</th>
                  <th className="py-3.5 px-5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700 font-medium">
                {filteredItems.map((item) => {
                  const hasPending = (item.pending_items_count && item.pending_items_count > 0) || item.run_status === 'waiting'
                  const isCompleted = item.run_status === 'completed' && !hasPending
                  const targetRunPath = item.run_id
                    ? `/workspace/${item.workspace_id}/runs/${item.run_id}`
                    : `/workspace/${item.workspace_id}`

                  return (
                    <tr key={item.id} className="hover:bg-slate-50/80 transition-colors group">
                      {/* Document Name */}
                      <td className="py-3.5 px-5">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg bg-blue-50 border border-blue-100 flex items-center justify-center text-blue-600 shrink-0">
                            <FileText className="w-4 h-4" />
                          </div>
                          <div className="min-w-0">
                            <Link
                              to={targetRunPath}
                              className="text-sm font-bold text-slate-900 group-hover:text-blue-600 transition-colors capitalize tracking-tight truncate block"
                            >
                              {formatTitle(item.filename)}
                            </Link>
                            <span className="text-[11px] font-mono text-slate-400 truncate block">
                              {item.filename}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Status */}
                      <td className="py-3.5 px-4">
                        {hasPending ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                            Ready for review
                          </span>
                        ) : isCompleted ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                            Formatted
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
                            {item.processing_status || 'Draft'}
                          </span>
                        )}
                      </td>

                      {/* Scenes */}
                      <td className="py-3.5 px-4 text-slate-600">
                        {item.scenes_count ? `${item.scenes_count} scenes` : '—'}
                      </td>

                      {/* Workspace */}
                      <td className="py-3.5 px-4 text-slate-600 truncate max-w-[140px]">
                        {item.workspace_name}
                      </td>

                      {/* Uploaded */}
                      <td className="py-3.5 px-4 text-slate-500 whitespace-nowrap" title={formatDate(item.created_at)}>
                        {formatRelativeTime(item.created_at)}
                      </td>

                      {/* Action */}
                      <td className="py-3.5 px-5 text-right">
                        <Link
                          to={targetRunPath}
                          className="inline-flex items-center gap-1 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-semibold rounded-lg transition-colors"
                        >
                          <span>Open</span>
                          <ArrowUpRight className="w-3.5 h-3.5 text-slate-500" />
                        </Link>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
