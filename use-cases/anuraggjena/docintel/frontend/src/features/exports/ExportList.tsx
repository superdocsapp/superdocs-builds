import { useQuery } from '@tanstack/react-query'
import { exportApi, Export } from '../../core/api/exportApi'
import { formatDate } from '@/shared/utils/formatDate'

interface ExportListProps {
  workspaceId: string
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function ExportRow({ export: exportRecord }: { export: Export }) {
  const handleDownload = () => {
    exportApi.download(exportRecord.id, exportRecord.filename).catch(console.error)
  }

  return (
    <tr className="border-b border-gray-200 hover:bg-gray-50">
      <td className="py-3 px-4 text-sm font-medium text-gray-900">{exportRecord.filename}</td>
      <td className="py-3 px-4 text-sm text-gray-500 uppercase">{exportRecord.format}</td>
      <td className="py-3 px-4 text-sm text-gray-500">{formatFileSize(exportRecord.file_size)}</td>
      <td className="py-3 px-4 text-sm text-gray-500">{formatDate(exportRecord.created_at)}</td>
      <td className="py-3 px-4">
        <button
          onClick={handleDownload}
          className="text-blue-600 hover:text-blue-800 text-sm font-medium"
        >
          Download
        </button>
      </td>
    </tr>
  )
}

export function ExportList({ workspaceId }: ExportListProps) {
  const { data: exports, isLoading, error } = useQuery({
    queryKey: ['exports', workspaceId],
    queryFn: () => exportApi.listByWorkspace(workspaceId),
    enabled: !!workspaceId
  })

  if (isLoading) {
    return <div className="text-gray-500 py-4">Loading exports...</div>
  }

  if (error) {
    return <div className="text-red-500 py-4">Failed to load exports</div>
  }

  if (!exports || exports.length === 0) {
    return (
      <div className="text-gray-500 py-4 text-center">
        No exports yet. Export a review to generate a DOCX report.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-300 bg-gray-50">
            <th className="py-3 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Filename</th>
            <th className="py-3 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Format</th>
            <th className="py-3 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Size</th>
            <th className="py-3 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
            <th className="py-3 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
          </tr>
        </thead>
        <tbody>
          {exports.map((exp) => (
            <ExportRow key={exp.id} export={exp} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
