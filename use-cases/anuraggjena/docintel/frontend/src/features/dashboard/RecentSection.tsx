import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface RecentSectionProps {
  title: string
  children: React.ReactNode
  emptyState?: React.ReactNode
  viewAllHref?: string
  className?: string
  isEmpty?: boolean
}

export function RecentSection({
  title,
  children,
  emptyState,
  viewAllHref,
  className,
  isEmpty = false,
}: RecentSectionProps) {
  return (
    <section className={cn('rounded-lg border bg-card shadow-sm', className)}>
      <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <h2 className="text-sm font-medium">{title}</h2>
        {viewAllHref && (
          <Link
            to={viewAllHref}
            className="flex items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground"
          >
            View all
            <ChevronRight className="h-3.5 w-3.5" />
          </Link>
        )}
      </div>
      <div className="px-4 py-2">
        {isEmpty && emptyState ? emptyState : children}
      </div>
    </section>
  )
}
