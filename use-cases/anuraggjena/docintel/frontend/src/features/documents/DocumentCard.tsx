import React, { useEffect, useState } from 'react'
import { Document } from '@/core/api/documentApi'
import { documentApi } from '@/core/api/documentApi'
import { formatDate } from '@/shared/utils/formatDate'

interface DocumentCardProps {
  document: Document
  onDownload: (documentId: string, filename: string) => void
  onDelete: (documentId: string) => void
}

const ROLE_LABELS: Record<string, string> = {
  product_spec: 'Product Spec',
  ruling: 'Ruling',
  product_image: 'Product Image',
  other: 'Other',
}

function isImageDocument(document: Document): boolean {
  return document.document_role === 'product_image' || document.mime_type.startsWith('image/')
}

export const DocumentCard: React.FC<DocumentCardProps> = ({
  document,
  onDownload,
  onDelete,
}) => {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState(false)

  useEffect(() => {
    if (!isImageDocument(document)) {
      return
    }

    let cancelled = false
    let objectUrl: string | null = null

    documentApi
      .getContentBlob(document.id)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setPreviewUrl(objectUrl)
      })
      .catch(() => {
        if (!cancelled) setPreviewError(true)
      })

    return () => {
      cancelled = true
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
    }
  }, [document.id, document.mime_type, document.document_role])

  const getStatusBadge = (status: string) => {
    const colors = {
      pending: 'bg-yellow-100 text-yellow-800',
      processing: 'bg-blue-100 text-blue-800',
      completed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
    }
    return colors[status as keyof typeof colors] || 'bg-gray-100 text-gray-800'
  }

  return (
    <div className="bg-white p-4 rounded-lg shadow hover:shadow-md transition-shadow">
      {isImageDocument(document) && (
        <div className="mb-3">
          {previewUrl ? (
            <img
              src={previewUrl}
              alt={document.filename}
              className="w-full h-32 object-cover rounded border border-gray-200"
            />
          ) : previewError ? (
            <div className="w-full h-32 rounded border border-dashed border-gray-300 flex items-center justify-center text-xs text-gray-500">
              Image preview unavailable
            </div>
          ) : (
            <div className="h-32 w-full rounded border border-gray-200 bg-gray-50 motion-safe:animate-pulse" />
          )}
        </div>
      )}

      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-gray-900">{document.filename}</h3>
          <p className="text-sm text-gray-500 mt-1">{document.mime_type}</p>
          <p className="text-xs text-gray-400 mt-1">{formatDate(document.created_at)}</p>

          <div className="flex flex-wrap gap-2 mt-2">
            <span className="inline-block px-2 py-1 text-xs font-semibold rounded bg-indigo-50 text-indigo-700">
              {ROLE_LABELS[document.document_role ?? 'product_spec'] ?? document.document_role}
            </span>
            <span
              className={`inline-block px-2 py-1 text-xs font-semibold rounded ${getStatusBadge(
                document.processing_status
              )}`}
            >
              {document.processing_status}
            </span>
          </div>
        </div>
      </div>

      <div className="mt-4 flex space-x-2">
        <button
          onClick={() => onDownload(document.id, document.filename)}
          className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          Download
        </button>
        <button
          onClick={() => onDelete(document.id)}
          className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
        >
          Delete
        </button>
      </div>
    </div>
  )
}
