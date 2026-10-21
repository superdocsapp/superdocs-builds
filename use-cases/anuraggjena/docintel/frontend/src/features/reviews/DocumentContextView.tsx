import { useEffect, useRef } from 'react'
import { DiffText } from '@/shared/components/DiffText'
import { cn } from '@/lib/utils'
import { buildStitchedSections } from './buildDocumentDiff'

export interface DocumentClaimView {
  id: string
  description?: string
  current_html?: string
  proposed_html?: string
}

export interface DocumentContextViewProps {
  claims: DocumentClaimView[]
  activeIndex: number
  className?: string
}

export function DocumentContextView({ claims, activeIndex, className }: DocumentContextViewProps) {
  const sections = buildStitchedSections(claims, activeIndex)
  const activeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    activeRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [activeIndex])

  if (sections.length === 0) {
    return (
      <div className={cn('flex flex-1 items-center justify-center p-6 text-sm text-muted-foreground', className)}>
        No document content available for this review.
      </div>
    )
  }

  return (
    <div className={cn('flex-1 overflow-y-auto p-6', className)}>
      <div className="mx-auto max-w-3xl space-y-6">
        {sections.map((section, index) => (
          <div
            key={section.id}
            ref={section.isActive ? activeRef : undefined}
            className={cn(
              'rounded-lg border p-4 transition-colors',
              section.isActive ? 'border-amber-300 bg-amber-50/50' : 'border-border bg-background'
            )}
          >
            {section.heading && (
              <h3 className="mb-3 text-sm font-medium text-foreground">{section.heading}</h3>
            )}
            <p className="text-sm leading-relaxed text-foreground">
              <DiffText tokens={section.tokens} />
            </p>
            {section.isActive && (
              <p className="mt-2 text-xs text-amber-700">Active change {index + 1}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
