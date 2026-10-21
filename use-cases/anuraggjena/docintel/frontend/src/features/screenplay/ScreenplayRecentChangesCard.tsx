import { useState, useMemo } from 'react'
import { Eye, FileEdit, CheckCircle2, XCircle, Clock } from 'lucide-react'
import type { FormattingItem } from '@/core/api/screenplayApi'
import type { ChangeFilterTab } from './types'
import { formatChangeReasonTitle } from './screenplayUtils'
import { cn } from '@/lib/utils'

interface ScreenplayRecentChangesCardProps {
  items: FormattingItem[]
  selectedItemIndex?: number
  onSelectItem?: (item: FormattingItem) => void
  onReviewChanges: () => void
  onViewAllChanges?: () => void
}

export function ScreenplayRecentChangesCard({
  items,
  selectedItemIndex,
  onSelectItem,
  onReviewChanges,
  onViewAllChanges,
}: ScreenplayRecentChangesCardProps) {
  const [filterTab, setFilterTab] = useState<ChangeFilterTab>('all')

  // Filter out items that had no changes at all
  const changedItems = useMemo(() => {
    return items.filter(
      (it) => it.change_type !== 'no_change' || it.status !== 'approved' || (it.reason && it.reason.trim())
    )
  }, [items])

  const pendingCount = changedItems.filter((it) => it.status === 'pending').length
  const acceptedCount = changedItems.filter((it) => it.status === 'approved').length

  const filteredItems = useMemo(() => {
    switch (filterTab) {
      case 'accepted':
        return changedItems.filter((it) => it.status === 'approved')
      case 'pending':
        return changedItems.filter((it) => it.status === 'pending')
      case 'rejected':
        return changedItems.filter((it) => it.status === 'rejected')
      default:
        return changedItems
    }
  }, [changedItems, filterTab])

  const displayItems = filteredItems.slice(0, 5)

  return (
    <div className="bg-white border border-slate-200/90 rounded-xl shadow-[0_1px_2px_rgba(0,0,0,0.02)] flex flex-col overflow-hidden min-h-[280px] shrink-0 lg:shrink lg:flex-1">
      {/* Header */}
      <div className="p-3.5 pb-2 border-b border-slate-100 flex items-center justify-between shrink-0">
        <h2 className="text-sm font-bold text-slate-900 tracking-tight">Recent Changes</h2>
        {changedItems.length > 5 && (
          <button
            type="button"
            onClick={onViewAllChanges}
            className="text-xs font-semibold text-blue-600 hover:text-blue-700 transition-colors cursor-pointer"
          >
            View all
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="px-3 pt-2 pb-1 flex items-center gap-1.5 border-b border-slate-100 bg-slate-50/40 shrink-0">
        <button
          type="button"
          onClick={() => setFilterTab('all')}
          className={cn(
            'px-2.5 py-1 rounded-md text-xs font-semibold transition-all cursor-pointer',
            filterTab === 'all'
              ? 'bg-white text-slate-900 shadow-xs'
              : 'text-slate-600 hover:text-slate-900'
          )}
        >
          All
        </button>

        <button
          type="button"
          onClick={() => setFilterTab('accepted')}
          className={cn(
            'px-2.5 py-1 rounded-md text-xs font-semibold transition-all cursor-pointer',
            filterTab === 'accepted'
              ? 'bg-white text-emerald-800 shadow-xs'
              : 'text-slate-600 hover:text-slate-900'
          )}
        >
          Accepted ({acceptedCount})
        </button>

        <button
          type="button"
          onClick={() => setFilterTab('pending')}
          className={cn(
            'px-2.5 py-1 rounded-md text-xs font-semibold transition-all cursor-pointer',
            filterTab === 'pending'
              ? 'bg-white text-amber-800 shadow-xs'
              : 'text-slate-600 hover:text-slate-900'
          )}
        >
          Pending ({pendingCount})
        </button>
      </div>

      {/* Changes List */}
      <div className="p-2 space-y-1 flex-1 min-h-[140px] overflow-y-auto">
        {displayItems.length === 0 ? (
          <div className="p-6 text-center text-slate-400 text-xs">
            <FileEdit className="w-5 h-5 mx-auto mb-1 text-slate-300" />
            <p>No changes in this filter</p>
          </div>
        ) : (
          displayItems.map((item) => {
            const isSelected = selectedItemIndex === item.element_index
            const title = formatChangeReasonTitle(item)
            const sceneInfo = `Scene ${item.scene_number || 1} • Line ${item.element_index + 1}`

            return (
              <button
                key={item.id || item.element_index}
                type="button"
                onClick={() => onSelectItem?.(item)}
                className={cn(
                  'w-full text-left p-2.5 rounded-lg flex items-center justify-between gap-3 transition-colors cursor-pointer',
                  isSelected
                    ? 'bg-blue-50 border border-blue-200'
                    : 'hover:bg-slate-50 border border-transparent'
                )}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-6 h-6 rounded-md bg-slate-100 text-slate-600 flex items-center justify-center shrink-0">
                    <FileEdit className="w-3.5 h-3.5" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-slate-900 truncate">
                      {title}
                    </p>
                    <p className="text-[10px] text-slate-400 mt-0.5 truncate">
                      {sceneInfo}
                    </p>
                  </div>
                </div>

                {/* Status Badge */}
                <div className="shrink-0">
                  {item.status === 'approved' ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200/60">
                      <CheckCircle2 className="w-3 h-3 stroke-[2.5]" />
                      <span>Accepted</span>
                    </span>
                  ) : item.status === 'rejected' ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-50 text-rose-700 border border-rose-200/60">
                      <XCircle className="w-3 h-3 stroke-[2.5]" />
                      <span>Rejected</span>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-200/60">
                      <Clock className="w-3 h-3 stroke-[2.5]" />
                      <span>Pending</span>
                    </span>
                  )}
                </div>
              </button>
            )
          })
        )}
      </div>

      {/* Review Changes Action Button */}
      <div className="p-3 border-t border-slate-100 bg-slate-50/50 shrink-0">
        <button
          type="button"
          onClick={onReviewChanges}
          className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs font-semibold rounded-lg shadow-sm transition-all cursor-pointer"
        >
          <Eye className="w-4 h-4 stroke-[2.2]" />
          <span>
            {pendingCount > 0
              ? `Review Changes (${pendingCount} pending)`
              : 'Review formatting changes'}
          </span>
        </button>
      </div>
    </div>
  )
}
