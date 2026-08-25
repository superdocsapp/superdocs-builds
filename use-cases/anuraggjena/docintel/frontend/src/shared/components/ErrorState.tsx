import { AlertCircle } from 'lucide-react'
import { Button } from '@/shared/components/ui/button'
import { TechnicalDetails } from '@/shared/components/TechnicalDetails'
import { cn } from '@/lib/utils'

export interface ErrorStateProps {
  title: string
  description: string
  onRetry: () => void
  error?: unknown
  className?: string
}

function formatError(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  try {
    return JSON.stringify(error, null, 2)
  } catch {
    return String(error)
  }
}

export function ErrorState({ title, description, onRetry, error, className }: ErrorStateProps) {
  const technicalDetails = error !== undefined ? formatError(error) : null

  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-lg border px-6 py-10 text-center',
        className
      )}
    >
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10">
        <AlertCircle className="h-5 w-5 text-destructive" />
      </div>
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      <Button type="button" variant="outline" size="sm" className="mt-4" onClick={onRetry}>
        Try again
      </Button>
      {technicalDetails && (
        <div className="mt-4 w-full max-w-lg text-left">
          <TechnicalDetails copyText={technicalDetails}>{technicalDetails}</TechnicalDetails>
        </div>
      )}
    </div>
  )
}
