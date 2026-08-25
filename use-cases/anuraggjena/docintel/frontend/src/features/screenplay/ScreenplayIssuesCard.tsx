import { CheckCircle2 } from 'lucide-react'
import type { ScreenplayIssueCategory } from './types'
import { cn } from '@/lib/utils'

interface ScreenplayIssuesCardProps {
  issues: ScreenplayIssueCategory[]
}

export function ScreenplayIssuesCard({
  issues,
}: ScreenplayIssuesCardProps) {
  const totalIssueCount = issues.reduce((acc, issue) => acc + issue.count, 0)

  return (
    <div className="bg-white border border-slate-200/90 rounded-xl shadow-[0_1px_2px_rgba(0,0,0,0.02)] p-3.5 space-y-2.5 shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold text-slate-900 tracking-tight">
            Potential Issues
          </h2>
          {totalIssueCount > 0 && (
            <span className="px-1.5 py-0.5 rounded text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200/60">
              {totalIssueCount}
            </span>
          )}
        </div>
      </div>

      {/* Issues List */}
      <div className="space-y-1.5">
        {totalIssueCount === 0 ? (
          <div className="p-2.5 bg-emerald-50/60 border border-emerald-100 rounded-lg flex items-center gap-2 text-xs text-emerald-800">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 stroke-[2.5]" />
            <span>No formatting issues detected. Compliant with standard rules.</span>
          </div>
        ) : (
          issues.map((issue) => (
            <div
              key={issue.id}
              className="flex items-center justify-between p-1.5 px-2 rounded-lg hover:bg-slate-50 transition-colors text-xs"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <span className={cn('w-2 h-2 rounded-full shrink-0', issue.dotColor)} />
                <span className="font-medium text-slate-800 truncate">
                  {issue.title}
                </span>
              </div>
              <span className="text-xs font-semibold text-slate-500 shrink-0 ml-2">
                {issue.count}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
