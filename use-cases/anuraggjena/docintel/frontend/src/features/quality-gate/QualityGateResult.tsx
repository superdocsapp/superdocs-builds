import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'

import {
  qualityGateApi,
  type QualityGateCheckDetail,
  type QualityGateResult as QualityGateResultData,
} from '@/core/api/qualityGateApi'
import { cn } from '@/lib/utils'
import { Skeleton } from '@/shared/components/ui/skeleton'

interface QualityGateResultProps {
  workflowRunId: string | null
}

const CHECK_NAME_LABELS: Record<string, string> = {
  baseline_contradiction: 'Baseline Contradiction',
  contradiction_detection: 'Contradiction Detection',
  memo_grounding: 'Memo Grounding',
  grounding: 'Evidence Grounding',
  citations: 'Citation Coverage',
}

function formatCheckName(checkName: string): string {
  if (CHECK_NAME_LABELS[checkName]) {
    return CHECK_NAME_LABELS[checkName]
  }
  return checkName
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function formatHumanMessage(rawMessage: string): string {
  const msg = rawMessage.trim()
  if (/no memo sections to validate/i.test(msg)) {
    return 'There were no memo sections available for this check.'
  }
  if (/no baseline|no previous classification/i.test(msg)) {
    return 'No previous classification exists for comparison.'
  }
  if (/all citations validated|passed|grounded/i.test(msg)) {
    return 'All claims and statements are grounded in retrieved evidence.'
  }
  return msg || 'Check evaluated successfully.'
}

function getOverallBadge(result: QualityGateResultData) {
  if (result.status === 'passed' || result.status === 'skipped') {
    return {
      label: 'All checks passed',
      style: 'bg-emerald-50 text-emerald-800 border-emerald-200/80',
    }
  }
  if (result.status === 'failed') {
    return {
      label: 'Quality check failed',
      style: 'bg-rose-50 text-rose-800 border-rose-200/80',
    }
  }
  return {
    label: 'Attention needed',
    style: 'bg-amber-50 text-amber-800 border-amber-200/80',
  }
}

function CheckCard({ check }: { check: QualityGateCheckDetail }) {
  const isFailed = check.status === 'failed'
  const isWarning = check.status === 'warning'
  const isPassed = check.status === 'passed'
  const isSkipped = check.status === 'skipped' || (!isFailed && !isWarning && !isPassed)

  const message = formatHumanMessage(check.message)

  return (
    <div
      className={cn(
        'flex items-start gap-3 p-3.5 rounded-xl border text-xs transition-colors',
        isFailed && 'bg-rose-50/50 border-rose-200 text-rose-950',
        isWarning && 'bg-amber-50/50 border-amber-200/80 text-amber-950',
        isSkipped && 'bg-slate-50/70 border-slate-200/80 text-slate-700',
        isPassed && 'bg-emerald-50/50 border-emerald-200/80 text-emerald-950'
      )}
    >
      <div className="mt-0.5 shrink-0">
        {isFailed && <XCircle className="w-4 h-4 text-rose-600" />}
        {isWarning && <AlertTriangle className="w-4 h-4 text-amber-600" />}
        {isSkipped && <CheckCircle2 className="w-4 h-4 text-slate-400" />}
        {isPassed && <CheckCircle2 className="w-4 h-4 text-emerald-600" />}
      </div>

      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center justify-between gap-2">
          <span className="font-bold text-slate-900">{formatCheckName(check.check_name)}</span>
          {isSkipped && (
            <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
              Not applicable
            </span>
          )}
          {check.blocking && (
            <span className="text-[10px] font-bold text-rose-600 uppercase">Blocking</span>
          )}
        </div>
        <p className="text-slate-600 leading-relaxed font-normal">{message}</p>
      </div>
    </div>
  )
}

export function QualityGateResult({ workflowRunId }: QualityGateResultProps) {
  const { data: result, isLoading } = useQuery({
    queryKey: ['quality-gate-result', workflowRunId],
    queryFn: () => qualityGateApi.getRunResult(workflowRunId!),
    enabled: !!workflowRunId,
  })

  if (!workflowRunId) return null
  if (isLoading) {
    return (
      <div className="bg-white border border-slate-200/90 rounded-2xl p-5 sm:p-6 shadow-xs space-y-3">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-16 w-full rounded-xl" />
      </div>
    )
  }
  if (!result) return null

  const badge = getOverallBadge(result)

  return (
    <div className="bg-white border border-slate-200/90 rounded-2xl p-5 sm:p-6 shadow-xs space-y-4">
      <div className="flex items-center justify-between gap-2 pb-2 border-b border-slate-100">
        <div>
          <h3 className="text-sm font-bold text-slate-900 tracking-tight">Quality Check</h3>
          <p className="text-xs text-slate-500 mt-0.5">Review the quality check results below.</p>
        </div>
        <span className={cn('rounded-full border px-2.5 py-0.5 text-xs font-semibold shrink-0', badge.style)}>
          {badge.label}
        </span>
      </div>

      {result.details.length > 0 ? (
        <div className="space-y-2.5">
          {result.details.map((check, index) => (
            <CheckCard key={`${check.check_name}-${index}`} check={check} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-400">No automated checks were registered for this run.</p>
      )}
    </div>
  )
}
