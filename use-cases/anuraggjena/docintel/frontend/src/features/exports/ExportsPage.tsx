import { useParams, Link } from 'react-router-dom'
import { FolderDown, ArrowLeft } from 'lucide-react'
import { ExportList } from './ExportList'

export function ExportsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()

  return (
    <div className="space-y-6 max-w-6xl mx-auto pb-10">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-amber-50 text-amber-600 border border-amber-100 flex items-center justify-center">
              <FolderDown className="w-4 h-4 stroke-[2]" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Exports</h1>
          </div>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Download generated DOCX screenplay documents and formatted exports.
          </p>
        </div>

        <Link
          to={`/workspace/${workspaceId}`}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 hover:text-slate-900 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Screenplay</span>
        </Link>
      </div>

      {/* Exports Table Card */}
      <div className="bg-white border border-slate-200/90 rounded-2xl p-6 shadow-sm">
        {workspaceId && <ExportList workspaceId={workspaceId} />}
      </div>
    </div>
  )
}
