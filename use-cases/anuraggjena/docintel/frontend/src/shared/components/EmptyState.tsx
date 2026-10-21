import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface EmptyStateProps {
  icon: LucideIcon
  title: string
  description: string
  action?: React.ReactNode
  className?: string
}

export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-lg border border-dashed px-6 py-12 text-center',
        className
      )}
    >
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-muted">
        <Icon className="h-5 w-5 text-muted-foreground" />
      </div>
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
