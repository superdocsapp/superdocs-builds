import { cn } from '@/lib/utils'

export type LiveIndicatorState = 'live' | 'reconnecting' | 'polling' | 'hidden'

interface LiveIndicatorProps {
  state: LiveIndicatorState
  className?: string
}

const STATE_CONFIG: Record<
  Exclude<LiveIndicatorState, 'hidden'>,
  { label: string; dotClass: string }
> = {
  live: {
    label: 'Live',
    dotClass: 'bg-green-500',
  },
  reconnecting: {
    label: 'Reconnecting',
    dotClass: 'bg-amber-500 motion-safe:animate-pulse',
  },
  polling: {
    label: 'Polling',
    dotClass: 'bg-slate-400',
  },
}

export function LiveIndicator({ state, className }: LiveIndicatorProps) {
  if (state === 'hidden') {
    return null
  }

  const config = STATE_CONFIG[state]

  return (
    <div
      className={cn(
        'flex items-center gap-2 text-xs text-muted-foreground',
        className
      )}
    >
      <span
        className={cn('h-2 w-2 rounded-full', config.dotClass)}
        aria-hidden
      />
      <span>{config.label}</span>
    </div>
  )
}
