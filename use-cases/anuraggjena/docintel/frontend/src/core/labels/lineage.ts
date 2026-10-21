const NODE_TYPE: Record<string, string> = {
  document: 'Source Document',
  chunk: 'Document Chunk',
  evidence: 'Evidence',
  claim: 'Classification Claim',
  memo_section: 'Memo Section',
  analysis: 'Analysis / Finding',
  knowledge: 'Knowledge Base',
  review: 'Approved Decision',
  workflow_run: 'Workflow Run',
  superdocs_change: 'Document Edit',
}

const EDGE_TYPE: Record<string, string> = {
  extracted_from: 'Extracted from',
  cited_by: 'Cites evidence',
  derived_from: 'Derived from',
  approved: 'Approved',
  rejected: 'Rejected',
  regenerated_from: 'Regenerated from',
  produced_by: 'Produced by',
  contributed_to: 'Supports finding',
  from_document: 'Contained in document',
  reviewed: 'Approved decision',
  superdocs_edit: 'Document revision',
}

export function formatNodeType(type: string): string {
  return NODE_TYPE[type] ?? type.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

export function formatEdgeType(type: string): string {
  return EDGE_TYPE[type] ?? type.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}
