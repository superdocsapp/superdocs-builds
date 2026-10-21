const STAGE_LABELS: Record<string, string> = {
  superdocs_upload: 'Upload to SuperDocs',
  focused_update: 'Focused Update',
  discover_documents: 'Discover Documents',
  load_product_content: 'Load Product Content',
  load_ruling_content: 'Load Ruling Content',
  knowledge_retrieve: 'Knowledge Retrieval',
  extract_product_facts: 'Product Facts',
  extract_ruling_facts: 'Ruling Facts',
  reconcile_documents: 'Reconcile Documents',
  retrieve: 'Evidence Retrieval',
  generate_memo_sections: 'Memo Generation',
  citations: 'Citation Building',
  quality_gate: 'Quality Check',
  superdocs_instruction: 'Prepare Review',
  superdocs_approval: 'Human Review',
  superdocs_export: 'Export Document',
  knowledge_store: 'Store Knowledge',
  extract: 'Document Extraction',
  generate: 'Report Generation',
  human_review_required: 'Awaiting Human Review',
}

export function formatStageName(stageName: string, status?: string): string {
  if (stageName === 'superdocs_approval') {
    if (status === 'running') {
      return 'Processing Document Changes'
    }
    if (status === 'waiting') {
      return 'Waiting for Human Review'
    }
    return 'Human Review'
  }
  if (STAGE_LABELS[stageName]) {
    return STAGE_LABELS[stageName]
  }
  return stageName
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}
