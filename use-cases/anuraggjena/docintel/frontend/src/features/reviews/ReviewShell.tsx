import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Button } from '@/shared/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/shared/components/ui/sheet'

export interface ReviewShellProps {
  backHref: string
  reviewStatus: string
  changeIndex: number
  totalChanges: number
  statusMessage?: React.ReactNode
  headerActions?: React.ReactNode
  documentView: React.ReactNode
  inspector: React.ReactNode
  navigator: React.ReactNode
}

export function ReviewShell({
  backHref,
  reviewStatus,
  changeIndex,
  totalChanges,
  statusMessage,
  headerActions,
  documentView,
  inspector,
  navigator,
}: ReviewShellProps) {
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const changeLabel = totalChanges > 0 ? `Change ${changeIndex + 1} of ${totalChanges}` : null

  return (
    <div className="flex min-h-[calc(100vh-8rem)] flex-col rounded-lg border bg-background">
      <header className="flex flex-col gap-3 border-b px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-2">
          <Link
            to={backHref}
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to run
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-lg font-semibold">Document Review</h1>
            {changeLabel && (
              <span className="text-sm text-muted-foreground">{changeLabel}</span>
            )}
            <StatusBadge status={reviewStatus} type="review" />
          </div>
          {statusMessage && <div className="text-sm text-muted-foreground">{statusMessage}</div>}
        </div>
        <div className="flex items-center gap-2">
          {headerActions}
          <Sheet open={inspectorOpen} onOpenChange={setInspectorOpen}>
            <SheetTrigger asChild>
              <Button type="button" variant="outline" size="sm" className="lg:hidden">
                Inspect change
              </Button>
            </SheetTrigger>
            <SheetContent side="bottom" className="h-[85vh] p-0">
              <SheetHeader className="border-b px-4 py-3 text-left">
                <SheetTitle>Change details</SheetTitle>
              </SheetHeader>
              <div className="h-[calc(85vh-3.5rem)] overflow-hidden">{inspector}</div>
            </SheetContent>
          </Sheet>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {documentView}
        <aside className="hidden w-96 shrink-0 border-l lg:block">{inspector}</aside>
      </div>

      {navigator}
    </div>
  )
}
