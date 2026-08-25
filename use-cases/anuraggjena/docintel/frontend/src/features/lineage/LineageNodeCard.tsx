import { memo } from 'react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'

import type { LineageNode } from '@/core/api/lineageApi'
import { formatNodeType } from '@/core/labels/lineage'
import { cn } from '@/lib/utils'

export type LineageNodeData = {
  lineageNode: LineageNode
}

export function getNodeSubtitle(metadata?: Record<string, unknown>): string | undefined {
  if (!metadata) return undefined

  const parts: string[] = []
  const page = metadata.page_number ?? metadata.page
  if (page != null) {
    parts.push(`Page ${page}`)
  }

  const documentName = metadata.filename ?? metadata.document_name
  if (typeof documentName === 'string' && documentName.length > 0) {
    parts.push(documentName)
  }

  return parts.length > 0 ? parts.join(' · ') : undefined
}

function getNodeBadgeClass(type: string): string {
  switch (type) {
    case 'document':
      return 'bg-blue-100 text-blue-800 border-blue-200'
    case 'evidence':
      return 'bg-emerald-100 text-emerald-800 border-emerald-200'
    case 'claim':
    case 'analysis':
      return 'bg-purple-100 text-purple-800 border-purple-200'
    case 'memo_section':
      return 'bg-indigo-100 text-indigo-800 border-indigo-200'
    case 'review':
      return 'bg-amber-100 text-amber-800 border-amber-200'
    case 'knowledge':
      return 'bg-cyan-100 text-cyan-800 border-cyan-200'
    default:
      return 'bg-slate-100 text-slate-800 border-slate-200'
  }
}

function LineageNodeCardComponent({ data, selected }: NodeProps<Node<LineageNodeData>>) {
  const { lineageNode } = data
  const subtitle = getNodeSubtitle(lineageNode.metadata)
  const badgeClass = getNodeBadgeClass(lineageNode.type)

  return (
    <div
      className={cn(
        'w-[240px] rounded-lg border bg-background px-3 py-2 shadow-sm transition-colors',
        selected ? 'border-primary ring-2 ring-primary/30' : 'border-border hover:border-primary/40'
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground" />
      <div className="space-y-1.5">
        <div className="flex items-start justify-between gap-2">
          <p className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
            {lineageNode.label}
          </p>
          <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider border', badgeClass)}>
            {formatNodeType(lineageNode.type)}
          </span>
        </div>
        {subtitle && <p className="line-clamp-1 text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground" />
    </div>
  )
}

export const LineageNodeCard = memo(LineageNodeCardComponent)
