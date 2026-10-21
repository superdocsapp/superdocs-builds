import { useEffect, useState } from 'react'
import {
  FileText,
  Download,
  Trash2,
  Image as ImageIcon,
  CheckCircle2,
  Loader2,
  AlertCircle,
  Clock,
} from 'lucide-react'

import { type Document, documentApi } from '@/core/api/documentApi'
import { formatDocumentRole } from '@/core/labels'
import { formatRelativeTime } from '@/shared/utils/formatDate'

interface DocumentTableProps {
  documents: Document[]
  onDownload: (documentId: string, filename: string) => void
  onDelete: (documentId: string) => void
}

function renderStatusBadge(status: string) {
  switch (status?.toLowerCase()) {
    case 'ready':
    case 'completed':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200/60">
          <CheckCircle2 className="w-3.5 h-3.5 stroke-[2.5]" />
          <span>Ready</span>
        </span>
      )
    case 'processing':
    case 'pending':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200/60">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span className="capitalize">{status}</span>
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
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-200 capitalize">
          <Clock className="w-3 h-3" />
          <span>{status || 'Unknown'}</span>
        </span>
      )
  }
}

function renderRoleBadge(role?: string) {
  switch (role) {
    case 'product_spec':
    case 'product_specification':
    case 'product':
      return (
        <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200/60">
          Product Specification
        </span>
      )
    case 'classification_ruling':
    case 'ruling':
      return (
        <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold bg-purple-50 text-purple-700 border border-purple-200/60">
          Classification Ruling
        </span>
      )
    case 'product_image':
      return (
        <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200/60">
          Product Image
        </span>
      )
    default:
      return (
        <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-200/60">
          {formatDocumentRole(role ?? 'other')}
        </span>
      )
  }
}

function isImageDocument(document: Document): boolean {
  return (
    document.document_role === 'product_image' ||
    document.mime_type.startsWith('image/') ||
    /\.(png|jpg|jpeg|webp|gif|svg)$/i.test(document.filename)
  )
}

function DocumentThumbnail({ document }: { document: Document }) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const isImg = isImageDocument(document)

  useEffect(() => {
    if (!isImg) return

    let cancelled = false
    let objectUrl: string | null = null

    documentApi
      .getContentBlob(document.id)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setPreviewUrl(objectUrl)
      })
      .catch(() => {})

    return () => {
      cancelled = true
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
    }
  }, [document.id, isImg])

  if (isImg) {
    if (previewUrl) {
      return (
        <img
          src={previewUrl}
          alt={document.filename}
          className="w-9 h-9 shrink-0 rounded-xl object-cover border border-slate-200 shadow-xs"
        />
      )
    }
    return (
      <div className="w-9 h-9 rounded-xl bg-emerald-50 text-emerald-600 border border-emerald-100 flex items-center justify-center shrink-0">
        <ImageIcon className="w-4 h-4 stroke-[2]" />
      </div>
    )
  }

  return (
    <div className="w-9 h-9 rounded-xl bg-red-50 text-red-600 border border-red-100 flex items-center justify-center shrink-0">
      <FileText className="w-4 h-4 stroke-[2]" />
    </div>
  )
}

function DocumentActions({
  document,
  onDownload,
  onDelete,
}: {
  document: Document
  onDownload: (documentId: string, filename: string) => void
  onDelete: (documentId: string) => void
}) {
  return (
    <div className="flex items-center justify-end gap-1.5">
      <button
        type="button"
        onClick={() => onDownload(document.id, document.filename)}
        className="w-8 h-8 rounded-lg border border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-600 hover:text-slate-900 transition-colors flex items-center justify-center cursor-pointer shadow-xs"
        title="Download file"
      >
        <Download className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        onClick={() => onDelete(document.id)}
        className="w-8 h-8 rounded-lg border border-slate-200 hover:border-red-200 hover:bg-red-50 text-slate-400 hover:text-red-600 transition-colors flex items-center justify-center cursor-pointer shadow-xs"
        title="Delete document"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

export function DocumentTable({ documents, onDownload, onDelete }: DocumentTableProps) {
  return (
    <>
      {/* Desktop table */}
      <div className="hidden md:block bg-white border border-slate-200/90 rounded-2xl shadow-sm overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50/75">
              <th className="py-3.5 px-6 text-xs font-bold text-slate-600 uppercase tracking-wider">
                Document
              </th>
              <th className="py-3.5 px-6 text-xs font-bold text-slate-600 uppercase tracking-wider">
                Role / Type
              </th>
              <th className="py-3.5 px-6 text-xs font-bold text-slate-600 uppercase tracking-wider">
                Status
              </th>
              <th className="py-3.5 px-6 text-xs font-bold text-slate-600 uppercase tracking-wider">
                Uploaded
              </th>
              <th className="py-3.5 px-6 text-right text-xs font-bold text-slate-600 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {documents.map((document) => (
              <tr
                key={document.id}
                className="hover:bg-slate-50/70 transition-colors group"
              >
                <td className="py-4 px-6">
                  <div className="flex items-center gap-3.5 min-w-0">
                    <DocumentThumbnail document={document} />
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-900 group-hover:text-blue-600 transition-colors truncate max-w-sm lg:max-w-md">
                        {document.filename}
                      </p>
                      <p className="text-xs text-slate-400 font-mono mt-0.5">
                        ID: {document.id}
                      </p>
                    </div>
                  </div>
                </td>
                <td className="py-4 px-6 whitespace-nowrap">
                  {renderRoleBadge(document.document_role)}
                </td>
                <td className="py-4 px-6 whitespace-nowrap">
                  {renderStatusBadge(document.processing_status)}
                </td>
                <td className="py-4 px-6 whitespace-nowrap text-xs text-slate-500 font-medium">
                  {formatRelativeTime(document.created_at)}
                </td>
                <td className="py-4 px-6 whitespace-nowrap text-right">
                  <DocumentActions
                    document={document}
                    onDownload={onDownload}
                    onDelete={onDelete}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="space-y-3 md:hidden">
        {documents.map((document) => (
          <div
            key={document.id}
            className="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-sm space-y-3"
          >
            <div className="flex items-start gap-3">
              <DocumentThumbnail document={document} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-bold text-slate-900">
                  {document.filename}
                </p>
                <p className="text-xs text-slate-400 font-medium mt-0.5">
                  {formatRelativeTime(document.created_at)}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5 items-center">
                  {renderRoleBadge(document.document_role)}
                  {renderStatusBadge(document.processing_status)}
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-slate-100">
              <span className="text-[11px] font-mono text-slate-400 truncate max-w-[150px]">
                {document.id}
              </span>
              <DocumentActions
                document={document}
                onDownload={onDownload}
                onDelete={onDelete}
              />
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

