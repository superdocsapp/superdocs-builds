export type DiffTokenType = 'equal' | 'insert' | 'delete' | 'modified'

export interface DiffToken {
  type: DiffTokenType
  text: string
}

export interface StitchedSection {
  id: string
  heading?: string
  tokens: DiffToken[]
  isActive: boolean
}

export interface ParagraphDiff {
  originalTokens: DiffToken[]
  proposedTokens: DiffToken[]
  hasChanges: boolean
}

export function stripHtml(html: string): string {
  if (!html) return ''
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n\n')
    .replace(/<\/div>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+/g, ' ')
    .replace(/\n\s+\n/g, '\n\n')
    .trim()
}

export function splitIntoParagraphs(textOrHtml: string): string[] {
  if (!textOrHtml) return []
  
  // If text contains HTML paragraph tags
  if (/<p[^>]*>/i.test(textOrHtml)) {
    const matches = textOrHtml.match(/<p[^>]*>([\s\S]*?)<\/p>/gi)
    if (matches && matches.length > 0) {
      return matches.map((p) => stripHtml(p)).filter((t) => t.trim().length > 0)
    }
  }

  // Fallback: split on double newlines or single newlines
  const plain = stripHtml(textOrHtml)
  const paragraphs = plain.split(/\n\s*\n/)
  const result = paragraphs.map((p) => p.trim()).filter((p) => p.length > 0)
  return result.length > 0 ? result : [plain]
}

function tokenize(text: string): string[] {
  const trimmed = text.trim()
  if (!trimmed) return []
  return trimmed.split(/\s+/)
}

function lcsTable(a: string[], b: string[]): number[][] {
  const m = a.length
  const n = b.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }
  return dp
}

function mergeToken(tokens: DiffToken[], type: DiffTokenType, word: string): void {
  const last = tokens[tokens.length - 1]
  if (last && last.type === type) {
    last.text += ` ${word}`
  } else {
    tokens.push({ type, text: word })
  }
}

export function buildWordDiff(before: string, after: string): DiffToken[] {
  const a = tokenize(before)
  const b = tokenize(after)

  if (a.length === 0 && b.length === 0) return []
  if (a.length === 0) return [{ type: 'insert', text: after.trim() }]
  if (b.length === 0) return [{ type: 'delete', text: before.trim() }]

  const dp = lcsTable(a, b)
  const rawOps: Array<{ type: 'equal' | 'insert' | 'delete'; word: string }> = []
  let i = a.length
  let j = b.length

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      rawOps.push({ type: 'equal', word: a[i - 1] })
      i--
      j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      rawOps.push({ type: 'insert', word: b[j - 1] })
      j--
    } else {
      rawOps.push({ type: 'delete', word: a[i - 1] })
      i--
    }
  }

  rawOps.reverse()

  const tokens: DiffToken[] = []
  for (let idx = 0; idx < rawOps.length; idx++) {
    const op = rawOps[idx]
    mergeToken(tokens, op.type, op.word)
  }

  return tokens
}

export function getSideBySideTokens(before: string, after: string): {
  originalTokens: DiffToken[]
  proposedTokens: DiffToken[]
} {
  const rawDiff = buildWordDiff(before, after)

  const originalTokens: DiffToken[] = []
  const proposedTokens: DiffToken[] = []

  for (let i = 0; i < rawDiff.length; i++) {
    const token = rawDiff[i]
    if (token.type === 'equal') {
      originalTokens.push({ type: 'equal', text: token.text })
      proposedTokens.push({ type: 'equal', text: token.text })
    } else if (token.type === 'delete') {
      originalTokens.push({ type: 'delete', text: token.text })
      // Check if this delete is paired with a neighboring insert (modification)
      const nextToken = rawDiff[i + 1]
      if (nextToken && nextToken.type === 'insert') {
        proposedTokens.push({ type: 'modified', text: nextToken.text })
        i++ // advance past the paired insert
      }
    } else if (token.type === 'insert') {
      proposedTokens.push({ type: 'insert', text: token.text })
    }
  }

  return { originalTokens, proposedTokens }
}

export function buildParagraphDiffs(beforeHtmlOrText: string, afterHtmlOrText: string): ParagraphDiff[] {
  const beforeParas = splitIntoParagraphs(beforeHtmlOrText)
  const afterParas = splitIntoParagraphs(afterHtmlOrText)

  const maxLen = Math.max(beforeParas.length, afterParas.length)
  if (maxLen === 0) return []

  const diffs: ParagraphDiff[] = []

  for (let i = 0; i < maxLen; i++) {
    const b = beforeParas[i] ?? ''
    const a = afterParas[i] ?? ''

    if (!b && a) {
      diffs.push({
        originalTokens: [],
        proposedTokens: [{ type: 'insert', text: a }],
        hasChanges: true,
      })
    } else if (b && !a) {
      diffs.push({
        originalTokens: [{ type: 'delete', text: b }],
        proposedTokens: [],
        hasChanges: true,
      })
    } else if (b === a) {
      diffs.push({
        originalTokens: [{ type: 'equal', text: b }],
        proposedTokens: [{ type: 'equal', text: a }],
        hasChanges: false,
      })
    } else {
      const { originalTokens, proposedTokens } = getSideBySideTokens(b, a)
      const hasChanges = originalTokens.some((t) => t.type !== 'equal') || proposedTokens.some((t) => t.type !== 'equal')
      diffs.push({
        originalTokens,
        proposedTokens,
        hasChanges,
      })
    }
  }

  return diffs
}

export function buildStitchedSections(
  claims: Array<{ id: string; description?: string; current_html?: string; proposed_html?: string }>,
  activeIndex: number
): StitchedSection[] {
  if (claims.length === 0) return []

  if (claims.length === 1) {
    const claim = claims[0]
    const current = stripHtml(claim.current_html ?? '')
    const proposed = stripHtml(claim.proposed_html ?? '')
    return [{
      id: claim.id,
      heading: claim.description,
      tokens: buildWordDiff(current, proposed),
      isActive: true,
    }]
  }

  return claims.map((claim, index) => {
    const isActive = index === activeIndex
    const current = stripHtml(claim.current_html ?? '')
    const proposed = stripHtml(claim.proposed_html ?? '')

    if (isActive) {
      return {
        id: claim.id,
        heading: claim.description,
        tokens: buildWordDiff(current, proposed),
        isActive: true,
      }
    }

    return {
      id: claim.id,
      heading: claim.description,
      tokens: current ? [{ type: 'equal' as const, text: current }] : [],
      isActive: false,
    }
  })
}
