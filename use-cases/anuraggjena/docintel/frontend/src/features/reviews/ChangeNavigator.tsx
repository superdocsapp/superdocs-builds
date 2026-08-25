import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/shared/components/ui/button'

export interface ChangeNavigatorProps {
  currentIndex: number
  total: number
  onPrevious: () => void
  onNext: () => void
  className?: string
}

export function ChangeNavigator({
  currentIndex,
  total,
  onPrevious,
  onNext,
  className,
}: ChangeNavigatorProps) {
  if (total === 0) return null

  const isFirst = currentIndex <= 0
  const isLast = currentIndex >= total - 1

  return (
    <div
      className={cn(
        'flex items-center justify-between gap-4 border-t bg-background px-4 py-3',
        className
      )}
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onPrevious}
        disabled={isFirst}
        aria-label="Previous change"
      >
        <ChevronLeft className="h-4 w-4" />
        Previous
      </Button>

      <div className="flex items-center gap-1.5" role="tablist" aria-label="Change indicators">
        {Array.from({ length: total }).map((_, index) => (
          <span
            key={index}
            role="tab"
            aria-selected={index === currentIndex}
            aria-label={`Change ${index + 1} of ${total}`}
            className={cn(
              'h-2 w-2 rounded-full transition-colors',
              index === currentIndex ? 'bg-foreground' : 'bg-muted-foreground/30'
            )}
          />
        ))}
      </div>

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onNext}
        disabled={isLast}
        aria-label="Next change"
      >
        Next
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  )
}
