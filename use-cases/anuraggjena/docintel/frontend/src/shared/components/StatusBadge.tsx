import {
  AlertCircle,
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock,
  Loader2,
  PauseCircle,
  ShieldAlert,
  SkipForward,
  XCircle,
  type LucideIcon,
} from 'lucide-react'

import {
  formatClaimStatus,
  formatReviewStatus,
  formatRunStatus,
  formatStageStatus,
} from '@/core/labels'
import { cn } from '@/lib/utils'
import { Badge } from '@/shared/components/ui/badge'

type StatusType = 'run' | 'stage' | 'review' | 'claim'

const RUN_COLORS: Record<string, string> = {
  queued: 'border-transparent bg-slate-100 text-slate-700',
  running: 'border-transparent bg-blue-100 text-blue-700',
  waiting: 'border-transparent bg-purple-100 text-purple-700',
  completed: 'border-transparent bg-green-100 text-green-700',
  failed: 'border-transparent bg-red-100 text-red-700',
  cancelled: 'border-transparent bg-amber-100 text-amber-700',
  blocked: 'border-transparent bg-orange-100 text-orange-700',
}

const STAGE_COLORS: Record<string, string> = {
  queued: 'border-transparent bg-slate-100 text-slate-700',
  running: 'border-transparent bg-blue-100 text-blue-700',
  completed: 'border-transparent bg-green-100 text-green-700',
  skipped: 'border-transparent bg-slate-100 text-slate-500',
  escalated: 'border-transparent bg-purple-100 text-purple-700',
  blocked: 'border-transparent bg-orange-100 text-orange-700',
  failed: 'border-transparent bg-red-100 text-red-700',
}

const REVIEW_COLORS: Record<string, string> = {
  in_review: 'border-transparent bg-amber-100 text-amber-800',
  approved: 'border-transparent bg-green-100 text-green-800',
  rejected: 'border-transparent bg-red-100 text-red-800',
  escalated: 'border-transparent bg-purple-100 text-purple-800',
}

const CLAIM_COLORS: Record<string, string> = {
  pending: 'border-transparent bg-amber-100 text-amber-800',
  approved: 'border-transparent bg-green-100 text-green-800',
  rejected: 'border-transparent bg-red-100 text-red-800',
  edited: 'border-transparent bg-blue-100 text-blue-800',
  applied: 'border-transparent bg-green-100 text-green-800',
  rejected_applied: 'border-transparent bg-red-100 text-red-800',
}

const COLOR_MAPS: Record<StatusType, Record<string, string>> = {
  run: RUN_COLORS,
  stage: STAGE_COLORS,
  review: REVIEW_COLORS,
  claim: CLAIM_COLORS,
}

const FORMATTERS: Record<StatusType, (status: string) => string> = {
  run: formatRunStatus,
  stage: formatStageStatus,
  review: formatReviewStatus,
  claim: formatClaimStatus,
}

const RUN_ICONS: Record<string, LucideIcon> = {
  queued: Clock,
  running: Loader2,
  waiting: PauseCircle,
  completed: CheckCircle2,
  failed: XCircle,
  cancelled: Ban,
  blocked: ShieldAlert,
}

const STAGE_ICONS: Record<string, LucideIcon> = {
  queued: Clock,
  running: Loader2,
  completed: CheckCircle2,
  skipped: SkipForward,
  escalated: AlertTriangle,
  blocked: ShieldAlert,
  failed: XCircle,
}

const REVIEW_ICONS: Record<string, LucideIcon> = {
  in_review: AlertCircle,
  approved: CheckCircle2,
  rejected: XCircle,
  escalated: AlertTriangle,
}

const CLAIM_ICONS: Record<string, LucideIcon> = {
  pending: AlertCircle,
  approved: CheckCircle2,
  rejected: XCircle,
  edited: AlertCircle,
  applied: CheckCircle2,
  rejected_applied: XCircle,
}

const ICON_MAPS: Record<StatusType, Record<string, LucideIcon>> = {
  run: RUN_ICONS,
  stage: STAGE_ICONS,
  review: REVIEW_ICONS,
  claim: CLAIM_ICONS,
}

const DEFAULT_COLOR = 'border-transparent bg-slate-100 text-slate-700'
const DEFAULT_ICON = AlertCircle

export interface StatusBadgeProps {
  status: string
  type: StatusType
  className?: string
}

export function StatusBadge({ status, type, className }: StatusBadgeProps) {
  const label = FORMATTERS[type](status)
  const colorClass = COLOR_MAPS[type][status] ?? DEFAULT_COLOR
  const Icon = ICON_MAPS[type][status] ?? DEFAULT_ICON
  const spin = status === 'running'

  return (
    <Badge className={cn('gap-1', colorClass, className)} variant="outline">
      <Icon
        className={cn('h-3 w-3 shrink-0', spin && 'motion-safe:animate-spin')}
        aria-hidden
      />
      <span>{label}</span>
    </Badge>
  )
}
