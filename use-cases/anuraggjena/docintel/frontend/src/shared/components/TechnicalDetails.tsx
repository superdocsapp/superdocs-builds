import { useState } from 'react'
import { ChevronDown, Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/shared/components/ui/button'

export interface TechnicalDetailsProps {
  children: React.ReactNode
  label?: string
  copyText?: string
  className?: string
}

export function TechnicalDetails({
  children,
  label = 'View technical details',
  copyText,
  className,
}: TechnicalDetailsProps) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    if (!copyText) return
    try {
      await navigator.clipboard.writeText(copyText)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <details
      open={open}
      onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}
      className={cn('rounded-md border border-border', className)}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2 text-sm text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-1.5">
          <ChevronDown
            className={cn('h-4 w-4 shrink-0 transition-transform', open && 'rotate-180')}
          />
          {label}
        </span>
        {copyText && open && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2"
            onClick={(event) => {
              event.preventDefault()
              void handleCopy()
            }}
          >
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            <span className="sr-only">Copy</span>
          </Button>
        )}
      </summary>
      <div className="border-t border-border bg-muted/30 px-3 py-2">
        <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-xs text-muted-foreground">
          {children}
        </pre>
      </div>
    </details>
  )
}
