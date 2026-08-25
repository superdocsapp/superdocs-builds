import { Check, Loader2, Clock, X } from 'lucide-react'
import type { WorkflowStage } from '@/core/api/types'
import { cn } from '@/lib/utils'

interface ScreenplayStatusStripProps {
  runStatus?: string
  stages?: WorkflowStage[]
  documentCreatedAt?: string
}

interface StepItem {
  id: string
  title: string
  subtitle: string
  status: 'completed' | 'current' | 'pending' | 'waiting' | 'failed'
}

export function ScreenplayStatusStrip({
  runStatus = 'idle',
  stages = [],
  documentCreatedAt,
}: ScreenplayStatusStripProps) {
  const parseStage = stages.find((s) => s.stage_name === 'parse')
  const formatStage = stages.find((s) => s.stage_name === 'format')
  const diffStage = stages.find((s) => s.stage_name === 'diff')

  const isParseDone = parseStage?.status === 'completed'
  const isFormatDone = formatStage?.status === 'completed'
  const isDiffDone = diffStage?.status === 'completed'
  const isRunComplete = runStatus === 'completed'
  const isWaitingReview = runStatus === 'waiting' || runStatus === 'awaiting_review'
  const isQueued = runStatus === 'queued'
  const isFailed = runStatus === 'failed'

  const steps: StepItem[] = [
    {
      id: 'uploaded',
      title: 'Uploaded',
      subtitle: documentCreatedAt
        ? new Date(documentCreatedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
        : 'Script source',
      status: 'completed',
    },
    {
      id: 'parsed',
      title: 'Parsed & Analyzed',
      subtitle: isParseDone
        ? '100% elements'
        : parseStage?.status === 'running'
        ? 'Parsing screenplay…'
        : isQueued
        ? 'Waiting to start…'
        : isFailed && !isParseDone
        ? 'Failed'
        : 'Pending',
      status: isParseDone
        ? 'completed'
        : isFailed && !isParseDone
        ? 'failed'
        : parseStage?.status === 'running' || isQueued
        ? 'current'
        : 'pending',
    },
    {
      id: 'formatting',
      title: 'Formatting',
      subtitle: isFormatDone
        ? 'Applied standards'
        : formatStage?.status === 'running'
        ? 'Formatting screenplay…'
        : isParseDone && !isFailed
        ? 'Ready'
        : isFailed && isParseDone && !isFormatDone
        ? 'Failed'
        : 'Pending',
      status: isFormatDone
        ? 'completed'
        : isFailed && isParseDone && !isFormatDone
        ? 'failed'
        : formatStage?.status === 'running'
        ? 'current'
        : 'pending',
    },
    {
      id: 'review',
      title: 'Review',
      subtitle: isRunComplete
        ? 'Approved'
        : isWaitingReview
        ? 'Ready for review'
        : diffStage?.status === 'running'
        ? 'Reviewing formatting…'
        : isDiffDone
        ? 'In review'
        : isFailed && isFormatDone && !isDiffDone
        ? 'Failed'
        : 'Pending',
      status: isRunComplete
        ? 'completed'
        : isFailed && isFormatDone && !isDiffDone
        ? 'failed'
        : isWaitingReview
        ? 'waiting'
        : diffStage?.status === 'running' || isDiffDone
        ? 'current'
        : 'pending',
    },
    {
      id: 'validation',
      title: 'Validation',
      subtitle: isRunComplete ? 'Passed' : isFormatDone ? 'No drift detected' : 'Pending',
      status: isRunComplete ? 'completed' : isFormatDone ? 'completed' : 'pending',
    },
    {
      id: 'export',
      title: 'Export',
      subtitle: isRunComplete ? 'DOCX ready' : 'Pending',
      status: isRunComplete ? 'completed' : 'pending',
    },
  ]

  return (
    <div className="bg-white border border-slate-200/90 rounded-xl px-5 py-3 shadow-[0_1px_2px_rgba(0,0,0,0.02)] overflow-x-auto">
      <div className="flex items-center justify-between min-w-[700px] relative">
        {/* Continuous background track line */}
        <div className="absolute top-3.5 left-6 right-6 h-0.5 bg-slate-100 -z-0" />

        {steps.map((step, index) => {
          const isCompleted = step.status === 'completed'
          const isCurrent = step.status === 'current'
          const isWaiting = step.status === 'waiting'
          const isFailedStep = step.status === 'failed'

          return (
            <div key={step.id} className="relative z-10 flex flex-col items-center text-center px-2 min-w-[100px]">
              {/* Step Circle Indicator */}
              <div
                className={cn(
                  'w-7 h-7 rounded-full flex items-center justify-center transition-all duration-200 text-xs font-bold border-2',
                  isCompleted && 'bg-blue-600 border-blue-600 text-white shadow-xs',
                  isWaiting && 'bg-emerald-500 border-emerald-500 text-white animate-pulse shadow-xs',
                  isCurrent && 'bg-white border-blue-600 text-blue-600 ring-2 ring-blue-100',
                  isFailedStep && 'bg-rose-600 border-rose-600 text-white shadow-xs',
                  !isCompleted && !isCurrent && !isWaiting && !isFailedStep && 'bg-white border-slate-200 text-slate-400'
                )}
              >
                {isCompleted ? (
                  <Check className="w-3.5 h-3.5 stroke-[3]" />
                ) : isFailedStep ? (
                  <X className="w-3.5 h-3.5 stroke-[3]" />
                ) : isWaiting ? (
                  <Clock className="w-3.5 h-3.5 stroke-[2.5]" />
                ) : isCurrent ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600" />
                ) : (
                  <span>{index + 1}</span>
                )}
              </div>

              {/* Step Labels */}
              <div className="mt-2 space-y-0.5">
                <p
                  className={cn(
                    'text-xs font-semibold leading-tight',
                    (isCompleted || isCurrent || isWaiting) ? 'text-slate-900' : isFailedStep ? 'text-rose-600' : 'text-slate-400'
                  )}
                >
                  {step.title}
                </p>
                <p className={cn('text-[11px] leading-tight', isFailedStep ? 'text-rose-500 font-medium' : 'text-slate-400')}>
                  {step.subtitle}
                </p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
