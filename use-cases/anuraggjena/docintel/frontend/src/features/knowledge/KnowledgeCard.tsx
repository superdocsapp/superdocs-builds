import { BookOpen, Clock } from 'lucide-react'

import type { KnowledgeEntry } from '@/core/api/knowledgeApi'
import { formatRelativeTime } from '@/shared/utils/formatDate'
import { cn } from '@/lib/utils'

import {
  formatEntryType,
  parseKnowledgeMetadata,
  truncateExcerpt,
} from './knowledgeHelpers'

export interface KnowledgeCardProps {
  entry: KnowledgeEntry
  onOpen: (entry: KnowledgeEntry) => void
}

function getEntryTypeStyle(type: string) {
  switch (type.toLowerCase()) {
    case 'claim':
      return 'bg-blue-50 text-blue-700 border-blue-200/60'
    case 'summary':
      return 'bg-purple-50 text-purple-700 border-purple-200/60'
    case 'full_output':
      return 'bg-emerald-50 text-emerald-700 border-emerald-200/60'
    default:
      return 'bg-slate-100 text-slate-700 border-slate-200/60'
  }
}

export function KnowledgeCard({ entry, onOpen }: KnowledgeCardProps) {
  const metadata = parseKnowledgeMetadata(entry.content)
  const excerpt = truncateExcerpt(entry.content)
  const typeStyle = getEntryTypeStyle(entry.entry_type)

  return (
    <article
      onClick={() => onOpen(entry)}
      className="bg-white border border-slate-200/90 hover:border-slate-300 rounded-2xl p-5 shadow-xs hover:shadow-sm transition-all duration-150 flex flex-col justify-between gap-4 group cursor-pointer"
    >
      <div className="space-y-3">
        {/* Header: Badge + Date */}
        <div className="flex items-center justify-between gap-2">
          <span
            className={cn(
              'inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold border capitalize',
              typeStyle
            )}
          >
            {formatEntryType(entry.entry_type)}
          </span>

          <div className="flex items-center gap-1 text-[11px] text-slate-400">
            <Clock className="w-3 h-3" />
            <span>{formatRelativeTime(entry.created_at)}</span>
          </div>
        </div>

        {/* Product / HS Code Box (if present) */}
        {(metadata.hsCode || metadata.productName) && (
          <div className="bg-slate-50 border border-slate-200/70 rounded-xl p-3 space-y-1">
            {metadata.productName && (
              <p className="text-xs font-bold text-slate-900 leading-snug">
                {metadata.productName}
              </p>
            )}
            {metadata.hsCode && (
              <div className="flex items-center gap-1.5 text-xs text-slate-600 font-mono">
                <span className="text-[11px] font-semibold text-slate-400 uppercase">HS:</span>
                <span className="font-bold text-blue-600">{metadata.hsCode}</span>
              </div>
            )}
          </div>
        )}

        {/* Content Excerpt */}
        <p className="text-xs text-slate-600 leading-relaxed line-clamp-4">
          {excerpt}
        </p>
      </div>

      <div className="space-y-3 pt-1 border-t border-slate-100">
        {/* Tags */}
        {entry.tags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            {entry.tags.slice(0, 4).map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium bg-slate-100 text-slate-600 border border-slate-200/60"
              >
                #{tag}
              </span>
            ))}
            {entry.tags.length > 4 && (
              <span className="text-[10px] text-slate-400 font-medium">
                +{entry.tags.length - 4} more
              </span>
            )}
          </div>
        )}

        {/* Action Button */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onOpen(entry)
          }}
          className="w-full inline-flex items-center justify-center gap-1.5 py-2 px-3 bg-slate-50 group-hover:bg-blue-50 group-hover:text-blue-600 text-slate-700 text-xs font-semibold rounded-xl border border-slate-200 group-hover:border-blue-200 transition-colors cursor-pointer"
        >
          <BookOpen className="w-3.5 h-3.5" />
          <span>Open full entry</span>
        </button>
      </div>
    </article>
  )
}

