import type { FormattingItem } from '@/core/api/screenplayApi'
import { formatElementType, getElementBadgeClass } from '@/core/labels'
import { cn } from '@/lib/utils'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { CheckCircle2 } from 'lucide-react'

export interface FormattingItemListProps {
  items: FormattingItem[]
  activeIndex: number
  onSelect: (index: number) => void
}

function truncate(text: string, maxLength = 80): string {
  if (!text) return ''
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength)}…`
}

export function FormattingItemList({ items, activeIndex, onSelect }: FormattingItemListProps) {
  if (items.length === 0) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center p-8 text-center text-muted-foreground">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400">
          <CheckCircle2 className="h-6 w-6" />
        </div>
        <h3 className="text-sm font-semibold text-foreground">No formatting changes proposed</h3>
        <p className="mt-1 text-xs max-w-sm">
          The document already conforms to industry standard screenplay format. No human approvals required.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col bg-muted/10">
      <div className="flex items-center justify-between border-b px-4 py-3 bg-card">
        <div>
          <h2 className="text-xs font-bold uppercase tracking-wider text-foreground">Formatting changes</h2>
          <p className="text-[11px] text-muted-foreground">
            {items.length} proposed {items.length === 1 ? 'change' : 'changes'} requiring review
          </p>
        </div>
      </div>
      <div className="divide-y">
        {items.map((item, index) => {
          const isActive = index === activeIndex
          const estimatedPage = item.element_index ? Math.max(1, Math.ceil((item.element_index + 1) / 45)) : 1
          const line = (item.element_index ?? index) + 1

          return (
            <button
              key={item.id || `change-${index}`}
              type="button"
              onClick={() => onSelect(index)}
              className={cn(
                'w-full p-4 text-left transition-all hover:bg-muted/40',
                isActive
                  ? 'border-l-4 border-l-primary bg-background shadow-sm'
                  : 'border-l-4 border-l-transparent bg-card/60'
              )}
            >
              {/* Header row: badge and location */}
              <div className="mb-2 flex flex-wrap items-center justify-between gap-1.5">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span
                    className={cn(
                      'rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide',
                      getElementBadgeClass(item.element_type)
                    )}
                  >
                    {formatElementType(item.element_type)}
                  </span>
                  <span className="text-[11px] font-medium text-muted-foreground">
                    Scene {item.scene_number ?? 1} · Page {estimatedPage} · Line {line}
                  </span>
                </div>
                <StatusBadge status={item.status} type="claim" className="text-[10px]" />
              </div>

              {/* Original snippet */}
              <div className="mt-2 space-y-1 text-xs">
                <div className="flex items-baseline gap-1.5 text-muted-foreground">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-rose-600 dark:text-rose-400">Original:</span>
                </div>
                <div className="rounded border border-rose-200/50 bg-rose-50/40 p-1.5 font-mono text-[11px] text-rose-950 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-200">
                  {truncate(item.original_text)}
                </div>

                {/* Proposed snippet */}
                <div className="flex items-baseline gap-1.5 text-muted-foreground pt-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">Proposed:</span>
                </div>
                <div className="rounded border border-emerald-200/50 bg-emerald-50/40 p-1.5 font-mono text-[11px] text-emerald-950 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200">
                  {truncate(item.formatted_text)}
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
