import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { FileText, Search, Upload, X, Filter } from 'lucide-react'

import { documentApi } from '@/core/api/documentApi'
import { useAuth } from '@/core/auth/AuthContext'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { ErrorState } from '@/shared/components/ErrorState'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { Skeleton } from '@/shared/components/ui/skeleton'

import { DocumentTable } from './DocumentTable'
import { DocumentUploadModal } from './DocumentUploadModal'
import { ROLE_OPTIONS } from './documentConstants'

type SortOption = 'newest' | 'oldest' | 'name'

export function DocumentsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const { accessToken } = useAuth()
  const queryClient = useQueryClient()

  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  const [sort, setSort] = useState<SortOption>('newest')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null)

  const {
    data: documents,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['documents', workspaceId],
    queryFn: () => documentApi.list(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const deleteMutation = useMutation({
    mutationFn: documentApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', workspaceId] })
      setDeleteTargetId(null)
    },
  })

  const filteredDocuments = useMemo(() => {
    if (!documents) return []

    let result = [...documents]

    if (search.trim()) {
      const query = search.trim().toLowerCase()
      result = result.filter((doc) => doc.filename.toLowerCase().includes(query))
    }

    if (roleFilter !== 'all') {
      result = result.filter((doc) => (doc.document_role ?? 'other') === roleFilter)
    }

    result.sort((a, b) => {
      if (sort === 'name') {
        return a.filename.localeCompare(b.filename)
      }
      const aTime = new Date(a.created_at).getTime()
      const bTime = new Date(b.created_at).getTime()
      return sort === 'newest' ? bTime - aTime : aTime - bTime
    })

    return result
  }, [documents, search, roleFilter, sort])

  const handleDownload = async (documentId: string, filename: string) => {
    try {
      await documentApi.download(documentId, filename)
    } catch (err) {
      console.error('Download failed:', err)
    }
  }

  const handleConfirmDelete = () => {
    if (deleteTargetId) {
      deleteMutation.mutate(deleteTargetId)
    }
  }

  const deleteTarget = documents?.find((doc) => doc.id === deleteTargetId)

  if (!workspaceId) {
    return null
  }

  return (
    <div className="space-y-6">
      {/* 1. Header Section */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
            Documents
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Manage product specifications, classification rulings, and reference files for this workspace.
          </p>
        </div>

        <div>
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs sm:text-sm font-semibold rounded-lg shadow-sm transition-all duration-150 cursor-pointer"
          >
            <Upload className="w-4 h-4 stroke-[2]" />
            <span>Upload document</span>
          </button>
        </div>
      </div>

      {/* 2. Filter & Search Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
        {/* Search Input */}
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
          <input
            type="text"
            placeholder="Search documents by filename…"
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

        {/* Role Filter */}
        <div className="w-full sm:w-[200px]">
          <Select value={roleFilter} onValueChange={setRoleFilter}>
            <SelectTrigger className="h-10 bg-white border-slate-200 rounded-xl text-xs text-slate-700 focus:ring-1 focus:ring-blue-600 focus:border-blue-600 cursor-pointer shadow-xs">
              <SelectValue placeholder="All types" />
            </SelectTrigger>
            <SelectContent className="bg-white border-slate-200 rounded-xl shadow-lg">
              <SelectItem value="all" className="text-xs">
                All document types
              </SelectItem>
              {ROLE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value} className="text-xs">
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Sort Option */}
        <div className="w-full sm:w-[170px]">
          <Select value={sort} onValueChange={(v) => setSort(v as SortOption)}>
            <SelectTrigger className="h-10 bg-white border-slate-200 rounded-xl text-xs text-slate-700 focus:ring-1 focus:ring-blue-600 focus:border-blue-600 cursor-pointer shadow-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-white border-slate-200 rounded-xl shadow-lg">
              <SelectItem value="newest" className="text-xs">
                Newest first
              </SelectItem>
              <SelectItem value="oldest" className="text-xs">
                Oldest first
              </SelectItem>
              <SelectItem value="name" className="text-xs">
                Name (A–Z)
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* 3. Document Content / Table / Empty States */}
      {isLoading ? (
        <div className="bg-white rounded-2xl border border-slate-200/90 shadow-sm p-4 space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <ErrorState
          title="Could not load documents"
          description="Something went wrong while fetching workspace documents."
          onRetry={() => refetch()}
          error={error}
        />
      ) : !documents || documents.length === 0 ? (
        <div className="bg-white border border-slate-200/90 rounded-2xl p-12 text-center shadow-sm">
          <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 border border-blue-100 flex items-center justify-center mx-auto mb-3">
            <FileText className="w-6 h-6 stroke-[1.75]" />
          </div>
          <h3 className="text-base font-bold text-slate-900 tracking-tight">
            No documents uploaded yet
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto mb-5">
            Upload product specifications, rulings, or images to begin running intelligence workflows.
          </p>
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs font-semibold rounded-lg shadow-sm transition-all cursor-pointer"
          >
            <Upload className="w-3.5 h-3.5 stroke-[2]" />
            <span>Upload first document</span>
          </button>
        </div>
      ) : filteredDocuments.length === 0 ? (
        <div className="bg-white border border-slate-200/90 rounded-2xl p-10 text-center shadow-sm">
          <div className="w-10 h-10 rounded-xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-2.5">
            <Filter className="w-5 h-5" />
          </div>
          <h3 className="text-sm font-bold text-slate-900">No matching documents</h3>
          <p className="text-xs text-slate-500 mt-0.5 mb-4">
            No documents matched your current search and filter criteria.
          </p>
          <button
            type="button"
            onClick={() => {
              setSearch('')
              setRoleFilter('all')
            }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors cursor-pointer"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <DocumentTable
          documents={filteredDocuments}
          onDownload={handleDownload}
          onDelete={setDeleteTargetId}
        />
      )}

      {/* Redesigned Upload Document Modal */}
      <DocumentUploadModal
        workspaceId={workspaceId}
        open={uploadOpen}
        onOpenChange={setUploadOpen}
      />

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={deleteTargetId !== null}
        title="Delete document"
        description={
          deleteTarget
            ? `Are you sure you want to delete "${deleteTarget.filename}"? This action cannot be undone.`
            : 'Are you sure you want to delete this document? This action cannot be undone.'
        }
        confirmLabel="Delete document"
        destructive
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTargetId(null)}
      />
    </div>
  )
}

