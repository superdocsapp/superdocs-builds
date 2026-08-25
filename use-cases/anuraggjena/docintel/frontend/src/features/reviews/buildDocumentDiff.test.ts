import { describe, it, expect } from 'vitest'
import {
  stripHtml,
  buildWordDiff,
  splitIntoParagraphs,
  getSideBySideTokens,
  buildParagraphDiffs,
} from './buildDocumentDiff'
import { parseReviewClaim } from './superdocsClaim'
import type { Claim } from '@/core/api/reviewApi'

describe('stripHtml', () => {
  it('removes tags and normalizes whitespace', () => {
    expect(stripHtml('<p>Hello <b>world</b></p>')).toBe('Hello world')
  })
})

describe('splitIntoParagraphs', () => {
  it('splits html paragraphs', () => {
    const html = '<p>First paragraph.</p><p>Second paragraph.</p>'
    expect(splitIntoParagraphs(html)).toEqual(['First paragraph.', 'Second paragraph.'])
  })

  it('splits newline separated paragraphs', () => {
    const text = 'First paragraph.\n\nSecond paragraph.'
    expect(splitIntoParagraphs(text)).toEqual(['First paragraph.', 'Second paragraph.'])
  })
})

describe('buildWordDiff', () => {
  it('marks insertions', () => {
    const tokens = buildWordDiff('the cat', 'the big cat')
    expect(tokens.some((t) => t.type === 'insert' && t.text.includes('big'))).toBe(true)
  })
  it('marks deletions', () => {
    const tokens = buildWordDiff('the big cat', 'the cat')
    expect(tokens.some((t) => t.type === 'delete')).toBe(true)
  })
})

describe('getSideBySideTokens', () => {
  it('marks replacements as modified on proposed side and deleted on original side', () => {
    const before = 'made primarily of 6016 aluminum'
    const after = 'made principally of 6061 aluminum'
    const { originalTokens, proposedTokens } = getSideBySideTokens(before, after)

    expect(originalTokens.some((t) => t.type === 'delete')).toBe(true)
    expect(proposedTokens.some((t) => t.type === 'modified' || t.type === 'insert')).toBe(true)
  })
})

describe('buildParagraphDiffs', () => {
  it('computes diff per paragraph correctly', () => {
    const orig = '<p>Para 1 unchanged</p><p>Para 2 old text</p>'
    const prop = '<p>Para 1 unchanged</p><p>Para 2 new text</p>'
    const diffs = buildParagraphDiffs(orig, prop)

    expect(diffs).toHaveLength(2)
    expect(diffs[0].hasChanges).toBe(false)
    expect(diffs[1].hasChanges).toBe(true)
  })
})

describe('parseReviewClaim', () => {
  it('parses superdocs json claim content into structured fields', () => {
    const claim: Claim = {
      id: 'claim-123',
      workflow_run_id: 'run-456',
      review_id: 'rev-789',
      claim_type: 'superdocs_change',
      content: JSON.stringify({
        superdocs_change_id: 'sd-change-1',
        chunk_id: 'chunk-sec-1',
        ai_explanation: 'Tariff analysis requires classification under 7616.99',
        old_html: '<p>Old content</p>',
        new_html: '<p>New content</p>',
      }),
      status: 'pending',
      original_content: null,
      edited_by: null,
      source_stage: 'superdocs_approval',
      created_at: '2026-08-21T19:07:00Z',
    }

    const parsed = parseReviewClaim(claim)
    expect(parsed.changeId).toBe('sd-change-1')
    expect(parsed.aiExplanation).toContain('7616.99')
    expect(parsed.oldText).toBe('Old content')
    expect(parsed.newText).toBe('New content')
    expect(parsed.changeType).toBe('modified')
    expect(parsed.originalLength).toBe(11)
    expect(parsed.proposedLength).toBe(11)
  })
})

