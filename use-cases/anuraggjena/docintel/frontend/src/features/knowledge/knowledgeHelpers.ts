export const ENTRY_TYPE_LABELS: Record<string, string> = {
  claim: 'Claim',
  summary: 'Summary',
  full_output: 'Full Output',
}

export const ENTRY_TYPE_OPTIONS = [
  { value: 'all', label: 'All types' },
  { value: 'claim', label: ENTRY_TYPE_LABELS.claim },
  { value: 'summary', label: ENTRY_TYPE_LABELS.summary },
  { value: 'full_output', label: ENTRY_TYPE_LABELS.full_output },
] as const

export function formatEntryType(entryType: string): string {
  return ENTRY_TYPE_LABELS[entryType] ?? entryType.replace(/_/g, ' ')
}

export function stripMarkdownForExcerpt(text: string): string {
  return text
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\n+/g, ' ')
    .trim()
}

export function truncateExcerpt(text: string, maxLength = 160): string {
  const plain = stripMarkdownForExcerpt(text)
  if (plain.length <= maxLength) return plain
  return `${plain.slice(0, maxLength).trimEnd()}…`
}

export interface KnowledgeMetadata {
  hsCode?: string
  productName?: string
}

export function parseKnowledgeMetadata(content: string): KnowledgeMetadata {
  try {
    const parsed = JSON.parse(content) as { hs_code?: string; description?: string }
    if (parsed.hs_code || parsed.description) {
      return {
        hsCode: parsed.hs_code,
        productName: parsed.description,
      }
    }
  } catch {
    // Not JSON — fall through to markdown/text parsing.
  }

  const hsMatch = content.match(/\b(\d{4}\.\d{2}(?:\.\d{2})?)\b/)
  const productHeading = content.match(/^#{1,6}\s+(.+)$/m)
  const productLine = content.match(/(?:product|description)[:\s-]+(.+)/i)

  return {
    hsCode: hsMatch?.[1],
    productName: productHeading?.[1]?.trim() || productLine?.[1]?.trim(),
  }
}

export function contentToMarkdown(content: string): string {
  try {
    const parsed = JSON.parse(content) as {
      hs_code?: string
      description?: string
      duty_rate?: string
      confidence_score?: number
    }

    if (parsed.hs_code || parsed.description) {
      const lines = ['### Classification Claim']
      if (parsed.hs_code) lines.push(`**HS Code:** ${parsed.hs_code}`)
      if (parsed.description) lines.push(`**Product:** ${parsed.description}`)
      if (parsed.duty_rate) lines.push(`**Duty Rate:** ${parsed.duty_rate}`)
      if (parsed.confidence_score != null) {
        lines.push(`**Confidence:** ${Math.round(parsed.confidence_score * 100)}%`)
      }
      return lines.join('\n\n')
    }
  } catch {
    // Not JSON — render as markdown.
  }

  return content
}
