import type { LineageEdge, LineageNode } from '@/core/api/lineageApi'
import { formatEdgeType, formatNodeType } from '@/core/labels/lineage'
import { TechnicalDetails } from '@/shared/components/TechnicalDetails'
import { StatusBadge } from '@/shared/components/StatusBadge'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/shared/components/ui/sheet'
import { FileText, ArrowRight, ArrowLeft, Sparkles } from 'lucide-react'
import { getNodeSubtitle } from './LineageNodeCard'

export interface LineageDetailDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  node: LineageNode | null
  edges?: LineageEdge[]
  nodesById?: Map<string, LineageNode>
}

export function LineageDetailDrawer({
  open,
  onOpenChange,
  node,
  edges = [],
  nodesById,
}: LineageDetailDrawerProps) {
  const subtitle = node ? getNodeSubtitle(node.metadata) : undefined

  const inboundEdges = node
    ? edges.filter((edge) => edge.target_id === node.id)
    : []

  const outboundEdges = node
    ? edges.filter((edge) => edge.source_id === node.id)
    : []

  const meta = (node?.metadata || {}) as Record<string, any>
  const status = meta.status || meta.processing_status
  const reasoning = meta.reasoning || meta.ai_explanation || meta.analyst_reasoning
  const summary = meta.summary || meta.description

  const technicalDetails = node
    ? JSON.stringify(
        {
          id: node.id,
          type: node.type,
          label: node.label,
          metadata: node.metadata ?? {},
        },
        null,
        2
      )
    : ''

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {node && (
          <div className="space-y-6 pb-6">
            <SheetHeader className="space-y-2">
              <div className="flex items-center justify-between gap-2 pr-6">
                <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-primary/10 text-primary border border-primary/20">
                  {formatNodeType(node.type)}
                </span>
                {status && <StatusBadge status={String(status)} type="claim" />}
              </div>
              <SheetTitle className="text-lg font-bold text-foreground text-left">
                {node.label}
              </SheetTitle>
              {subtitle && (
                <SheetDescription className="text-xs text-muted-foreground text-left">
                  {subtitle}
                </SheetDescription>
              )}
            </SheetHeader>

            <div className="space-y-5 divide-y divide-border pt-2">
              {/* 1. What is this? */}
              <div className="space-y-2 pt-3 first:pt-0">
                <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  <FileText className="h-3.5 w-3.5 text-primary" />
                  <h4>1. What is this?</h4>
                </div>
                <div className="rounded-lg bg-muted/40 p-3 text-xs leading-relaxed text-foreground space-y-2">
                  <p className="font-medium">{summary || node.label}</p>
                  {meta.mime_type && (
                    <p className="text-[11px] text-muted-foreground font-mono">
                      File type: {meta.mime_type}
                    </p>
                  )}
                  {meta.page_number != null && (
                    <p className="text-[11px] text-muted-foreground">
                      Page number: {meta.page_number}
                    </p>
                  )}
                </div>
              </div>

              {/* 2. Where did it come from? */}
              <div className="space-y-2 pt-4">
                <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  <ArrowLeft className="h-3.5 w-3.5 text-blue-600" />
                  <h4>2. Where did it come from?</h4>
                </div>
                {inboundEdges.length > 0 ? (
                  <div className="space-y-2">
                    {inboundEdges.map((edge, index) => {
                      const sourceNode = nodesById?.get(edge.source_id)
                      return (
                        <div
                          key={`in-${edge.source_id}-${index}`}
                          className="flex flex-col gap-1 rounded-lg border border-border bg-card p-2.5 text-xs"
                        >
                          <span className="font-semibold text-foreground">
                            {formatEdgeType(edge.edge_type)}
                          </span>
                          <span className="text-muted-foreground line-clamp-2">
                            {sourceNode?.label ?? edge.source_id}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground italic bg-muted/20 p-2.5 rounded-lg">
                    {meta.source_stage
                      ? `Originated during the ${meta.source_stage.replace(/_/g, ' ')} workflow stage.`
                      : 'Root source document in this workflow.'}
                  </p>
                )}
              </div>

              {/* 3. What does it support? */}
              <div className="space-y-2 pt-4">
                <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  <ArrowRight className="h-3.5 w-3.5 text-emerald-600" />
                  <h4>3. What does it support?</h4>
                </div>
                {outboundEdges.length > 0 ? (
                  <div className="space-y-2">
                    {outboundEdges.map((edge, index) => {
                      const targetNode = nodesById?.get(edge.target_id)
                      return (
                        <div
                          key={`out-${edge.target_id}-${index}`}
                          className="flex flex-col gap-1 rounded-lg border border-border bg-card p-2.5 text-xs"
                        >
                          <span className="font-semibold text-foreground">
                            {formatEdgeType(edge.edge_type)}
                          </span>
                          <span className="text-muted-foreground line-clamp-2">
                            {targetNode?.label ?? edge.target_id}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground italic bg-muted/20 p-2.5 rounded-lg">
                    Final conclusion node or terminal memo section in this run.
                  </p>
                )}
              </div>

              {/* 4. What did the workflow conclude from it? */}
              <div className="space-y-2 pt-4">
                <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  <Sparkles className="h-3.5 w-3.5 text-amber-600" />
                  <h4>4. What did the workflow conclude?</h4>
                </div>
                <div className="rounded-lg bg-muted/30 p-3 text-xs space-y-2">
                  {reasoning ? (
                    <p className="leading-relaxed text-foreground">{reasoning}</p>
                  ) : (
                    <p className="text-muted-foreground italic">
                      Verified and processed into the finalized classification memo.
                    </p>
                  )}
                  {meta.relevance_score != null && (
                    <div className="flex items-center gap-2 pt-1">
                      <span className="text-[11px] font-semibold text-muted-foreground">
                        Relevance Confidence:
                      </span>
                      <span className="font-mono text-xs font-bold text-foreground">
                        {typeof meta.relevance_score === 'number'
                          ? `${(meta.relevance_score * 100).toFixed(0)}%`
                          : meta.relevance_score}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Collapsed Technical Details */}
            <div className="pt-2">
              <TechnicalDetails label="Technical Details" copyText={technicalDetails}>
                {technicalDetails}
              </TechnicalDetails>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
