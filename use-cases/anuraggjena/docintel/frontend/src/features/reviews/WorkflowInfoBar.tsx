import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { StatusBadge } from '@/shared/components/StatusBadge'

export interface WorkflowInfoBarProps {
  runId: string
  workflowSlug?: string | null
  stageName?: string | null
  requestedAt: string
  requestedBy?: string | null
  reviewStatus: string
}

function formatRunDisplayId(runId: string, workflowSlug?: string | null): string {
  if (workflowSlug) {
    const prefix = workflowSlug === 'tariff_classification' ? 'TRF' : workflowSlug.slice(0, 3).toUpperCase()
    const cleanId = runId.replace(/-/g, '').slice(0, 8).toUpperCase()
    return `${prefix}-${cleanId}`
  }
  return `RUN-${runId.slice(0, 8).toUpperCase()}`
}

function formatRequestedDate(iso: string): string {
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    const datePart = d.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
    const timePart = d.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    })
    return `${datePart} at ${timePart}`
  } catch {
    return iso
  }
}

export function WorkflowInfoBar({
  runId,
  workflowSlug,
  stageName = 'Human Review',
  requestedAt,
  requestedBy = 'System',
  reviewStatus,
}: WorkflowInfoBarProps) {
  const [copied, setCopied] = useState(false)
  const displayRunId = formatRunDisplayId(runId, workflowSlug)

  const handleCopy = () => {
    navigator.clipboard.writeText(runId)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-5">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Workflow Run
          </p>
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-semibold text-foreground">{displayRunId}</span>
            <button
              type="button"
              onClick={handleCopy}
              className="text-muted-foreground hover:text-foreground transition-colors p-0.5 rounded"
              title="Copy full Run ID"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>

        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Stage
          </p>
          <p className="text-xs font-semibold text-foreground">
            {stageName || 'Human Review'}
          </p>
        </div>

        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Requested at
          </p>
          <p className="text-xs font-medium text-foreground">
            {formatRequestedDate(requestedAt)}
          </p>
        </div>

        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Requested by
          </p>
          <p className="text-xs font-medium text-foreground">
            {requestedBy || 'System'}
          </p>
        </div>

        <div className="space-y-1 col-span-2 sm:col-span-1">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Review status
          </p>
          <div>
            <StatusBadge status={reviewStatus} type="review" />
          </div>
        </div>
      </div>
    </div>
  )
}
