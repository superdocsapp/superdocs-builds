import type { LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface MetricCardProps {
  label: string
  count: number | string
  subtext?: string
  icon?: LucideIcon
  iconColor?: string
  iconBgColor?: string
  className?: string
}

export function MetricCard({
  label,
  count,
  subtext,
  icon: Icon,
  iconColor = 'text-blue-600',
  iconBgColor = 'bg-blue-50 border-blue-100',
  className,
}: MetricCardProps) {
  return (
    <div
      className={cn(
        'bg-white border border-slate-200/90 rounded-xl p-4 shadow-[0_1px_3px_rgba(0,0,0,0.02)] flex items-start gap-3.5',
        className
      )}
    >
      {Icon && (
        <div
          className={cn(
            'w-10 h-10 rounded-xl border flex items-center justify-center shrink-0 mt-0.5',
            iconBgColor,
            iconColor
          )}
        >
          <Icon className="w-5 h-5 stroke-[2]" />
        </div>
      )}
      <div className="min-w-0">
        <p className="text-xs font-semibold text-slate-500 tracking-tight">{label}</p>
        <p className="text-2xl font-bold text-slate-900 tracking-tight leading-tight mt-0.5">
          {count}
        </p>
        {subtext && (
          <p className="text-xs text-slate-400 mt-0.5 truncate">{subtext}</p>
        )}
      </div>
    </div>
  )
}

