import type { Claim } from '@/core/api/reviewApi'
import { stripHtml } from './buildDocumentDiff'

export interface SuperDocsChangePayload {
  superdocs_change_id?: string
  change_id?: string
  chunk_id?: string
  title?: string
  section?: string
  section_name?: string
  section_type?: string
  section_order?: number
  field?: string
  description?: string
  summary?: string
  proposed_html?: string
  current_html?: string
  old_html?: string
  new_html?: string
  old_content?: string
  new_content?: string
  content?: string
  content_preview?: string
  ai_explanation?: string
  analyst_reasoning?: string
  reason?: string
  explanation?: string
  rationale?: string
  page?: number | string
  page_number?: number | string
  document_name?: string
  type?: 'added' | 'removed' | 'modified'
  change_type?: 'added' | 'removed' | 'modified'
  confidence?: number | string
  [key: string]: unknown
}

export interface ParsedReviewClaim {
  id: string
  changeId: string
  chunkId: string
  section: string
  page: string
  documentName?: string
  oldHtml: string | null
  newHtml: string | null
  oldText: string
  newText: string
  aiExplanation: string | null
  changeType: 'added' | 'removed' | 'modified'
  status: string
  originalLength: number
  proposedLength: number
  rawContent: string
  rawPayload: SuperDocsChangePayload | null
}

function formatLabel(str: string): string {
  return str
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function isUuid(val: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(val.trim())
}

function tryParseJson(val: unknown): Record<string, any> | null {
  if (typeof val !== 'string') return null
  const trimmed = val.trim()
  if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
    try {
      return JSON.parse(trimmed)
    } catch {
      return null
    }
  }
  return null
}

export function parseSuperDocsClaimContent(content: string): SuperDocsChangePayload | null {
  if (!content) return null
  const parsed = tryParseJson(content)
  if (parsed && typeof parsed === 'object') {
    return parsed as SuperDocsChangePayload
  }
  return null
}

export function parseReviewClaim(claim: Claim): ParsedReviewClaim {
  const parsed = parseSuperDocsClaimContent(claim.content)

  // Determine new HTML
  let newHtml: string | null = null
  if (parsed) {
    newHtml =
      parsed.new_html ??
      parsed.new_content ??
      parsed.proposed_html ??
      parsed.content ??
      parsed.content_preview ??
      null
  } else if (claim.content && !claim.content.startsWith('{')) {
    newHtml = claim.content
  }

  // Determine old HTML
  let oldHtml: string | null = null
  if (parsed) {
    oldHtml =
      parsed.old_html ??
      parsed.old_content ??
      parsed.current_html ??
      null
  }

  // If oldHtml is still null, inspect claim.original_content
  if (!oldHtml && claim.original_content) {
    const origParsed = tryParseJson(claim.original_content)
    if (origParsed) {
      oldHtml =
        origParsed.old_html ??
        origParsed.old_content ??
        origParsed.current_html ??
        origParsed.content ??
        null
    } else if (!claim.original_content.startsWith('{')) {
      // Only treat original_content as oldHtml if it's not simply identical new content
      if (claim.original_content !== claim.content || parsed?.old_html) {
        oldHtml = claim.original_content
      }
    }
  }

  // AI Explanation
  const aiExplanation =
    parsed?.ai_explanation ??
    parsed?.analyst_reasoning ??
    parsed?.reason ??
    parsed?.explanation ??
    parsed?.rationale ??
    parsed?.description ??
    (claim.source_stage ? `Generated during ${formatLabel(claim.source_stage)} stage.` : null)

  const changeId = String(parsed?.superdocs_change_id ?? (parsed as Record<string, unknown>)?.memo_section_id ?? parsed?.change_id ?? claim.id)
  const chunkId = parsed?.chunk_id ? String(parsed.chunk_id) : ''

  // Section title
  let section = 'Document Change'
  if (parsed?.title) {
    section = parsed.title
  } else if (parsed?.section && !isUuid(parsed.section)) {
    section = parsed.section
  } else if (parsed?.section_name && !isUuid(parsed.section_name)) {
    section = parsed.section_name
  } else if (parsed?.section_type) {
    section = formatLabel(parsed.section_type)
  } else if (parsed?.field) {
    section = `Field: ${formatLabel(parsed.field)}`
  } else if (claim.claim_type && !isUuid(claim.claim_type)) {
    section = formatLabel(claim.claim_type)
  } else if (claim.source_stage) {
    section = formatLabel(claim.source_stage)
  }

  // Page / Section ordering
  let page = 'General'
  if (parsed?.page != null) {
    page = typeof parsed.page === 'number' ? `Page ${parsed.page}` : String(parsed.page)
  } else if (parsed?.page_number != null) {
    page = `Page ${parsed.page_number}`
  } else if (parsed?.section_order != null) {
    page = `Section ${parsed.section_order}`
  } else if (chunkId && !isUuid(chunkId)) {
    page = `Chunk ${chunkId}`
  } else if (claim.source_stage) {
    page = formatLabel(claim.source_stage)
  }

  // Document name
  let documentName = parsed?.document_name
  if (documentName && documentName.match(/\.(png|jpe?g|gif|webp|svg)$/i)) {
    documentName = undefined
  }

  const oldText = oldHtml ? stripHtml(oldHtml) : ''
  const newText = newHtml ? stripHtml(newHtml) : ''

  // Determine change type
  let changeType: 'added' | 'removed' | 'modified' = 'modified'
  if (parsed?.type === 'added' || parsed?.change_type === 'added') {
    changeType = 'added'
  } else if (parsed?.type === 'removed' || parsed?.change_type === 'removed') {
    changeType = 'removed'
  } else if (parsed?.type === 'modified' || parsed?.change_type === 'modified') {
    changeType = 'modified'
  } else if (!oldHtml && newHtml) {
    changeType = 'added'
  } else if (oldHtml && !newHtml) {
    changeType = 'removed'
  } else {
    changeType = 'modified'
  }

  return {
    id: claim.id,
    changeId,
    chunkId,
    section,
    page,
    documentName,
    oldHtml,
    newHtml,
    oldText,
    newText,
    aiExplanation,
    changeType,
    status: claim.status || 'pending',
    originalLength: oldText.length,
    proposedLength: newText.length,
    rawContent: typeof claim.content === 'string' ? claim.content : JSON.stringify(claim.content ?? ''),
    rawPayload: parsed,
  }
}

export { stripHtml } from './buildDocumentDiff'
