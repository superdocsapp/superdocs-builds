import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { ExternalLink, Trash2 } from 'lucide-react'

import type { KnowledgeEntry } from '@/core/api/knowledgeApi'
import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/shared/components/ui/sheet'
import { formatDate } from '@/shared/utils/formatDate'

import { contentToMarkdown, formatEntryType } from './knowledgeHelpers'

export interface KnowledgeDetailDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  entry: KnowledgeEntry | null
  workspaceId: string
  onDelete: (entry: KnowledgeEntry) => void
}

const markdownComponents = {
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="mb-3 mt-4 text-xl font-semibold first:mt-0">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="mb-2 mt-4 text-lg font-semibold first:mt-0">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="mb-2 mt-3 text-base font-semibold first:mt-0">{children}</h3>
  ),
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-3 text-sm leading-relaxed last:mb-0">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="mb-3 list-disc space-y-1 pl-5 text-sm last:mb-0">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm last:mb-0">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{children}</code>
  ),
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre className="mb-3 overflow-x-auto rounded-md bg-muted p-3 text-xs last:mb-0">{children}</pre>
  ),
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="mb-3 border-l-2 border-muted-foreground/30 pl-3 text-sm italic last:mb-0">
      {children}
    </blockquote>
  ),
}

export function KnowledgeDetailDrawer({
  open,
  onOpenChange,
  entry,
  workspaceId,
  onDelete,
}: KnowledgeDetailDrawerProps) {
  const markdown = entry ? contentToMarkdown(entry.content) : ''

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {entry && (
          <>
            <SheetHeader>
              <SheetTitle className="pr-8">{formatEntryType(entry.entry_type)}</SheetTitle>
              <SheetDescription asChild>
                <div className="space-y-2 text-left">
                  <Badge variant="secondary">{entry.workflow_type}</Badge>
                  <p className="text-sm text-muted-foreground">{formatDate(entry.created_at)}</p>
                </div>
              </SheetDescription>
            </SheetHeader>

            <div className="mt-6 space-y-4">
              {entry.confidence_score !== null && (
                <p className="text-sm text-muted-foreground">
                  Confidence: {Math.round(entry.confidence_score * 100)}%
                </p>
              )}

              {entry.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {entry.tags.map((tag) => (
                    <Badge key={tag} variant="outline" className="font-normal">
                      {tag}
                    </Badge>
                  ))}
                </div>
              )}

              {entry.source_run_id && (
                <Button asChild variant="outline" size="sm">
                  <Link to={`/workspace/${workspaceId}/runs/${entry.source_run_id}`}>
                    <ExternalLink className="h-4 w-4" />
                    View source run
                  </Link>
                </Button>
              )}

              <div className="rounded-md border p-4">
                <ReactMarkdown components={markdownComponents}>{markdown}</ReactMarkdown>
              </div>

              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={() => onDelete(entry)}
              >
                <Trash2 className="h-4 w-4" />
                Delete entry
              </Button>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
