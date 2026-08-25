import { describe, it, expect } from 'vitest'
import { parseClaim } from './HumanApprovalModal'
import type { RunClaim } from '@/core/api/workflowApi'

describe('HumanApprovalModal parseClaim', () => {
  it('parses tariff memo_section claims with full structured content', () => {
    const claim: RunClaim = {
      id: 'claim-123',
      claim_type: 'memo_section',
      content: JSON.stringify({
        memo_section_id: 'sec-456',
        section_type: 'product_overview',
        title: 'Product Overview & Specifications',
        section_order: 1,
        content: '<p>The device is a multi-function wireless router operating on 5GHz.</p>',
        new_html: '<p>The device is a multi-function wireless router operating on 5GHz.</p>',
        old_html: '<p>Legacy router operating on 2.4GHz.</p>',
        analyst_reasoning: 'Updated to reflect the latest technical specifications provided in the catalog.',
        ai_explanation: 'Updated to reflect the latest technical specifications provided in the catalog.',
        confidence: '0.94',
      }),
      status: 'pending',
      source_stage: 'generate_memo_sections',
      confidence_score: '0.94',
      original_content: null,
      review_id: 'rev-789',
      created_at: '2026-08-23T10:00:00Z',
    }

    const parsed = parseClaim(claim)
    expect(parsed.id).toBe('claim-123')
    expect(parsed.changeId).toBe('sec-456')
    expect(parsed.section).toBe('Product Overview & Specifications')
    expect(parsed.page).toBe('Section 1')
    expect(parsed.type).toBe('modified')
    expect(parsed.oldHtml).toContain('Legacy router operating on 2.4GHz.')
    expect(parsed.newHtml).toContain('The device is a multi-function wireless router')
    expect(parsed.aiExplanation).toContain('technical specifications')
    expect(parsed.status).toBe('pending')
  })

  it('correctly determines added vs removed vs modified type', () => {
    const addedClaim: RunClaim = {
      id: 'claim-add',
      claim_type: 'memo_section',
      content: JSON.stringify({
        title: 'Tariff Classification Analysis',
        new_html: '<p>HTS Code: 8517.62.0050</p>',
        old_html: null,
        ai_explanation: 'New classification rationale added.',
      }),
      status: 'pending',
      source_stage: null,
      confidence_score: null,
      original_content: null,
      review_id: null,
      created_at: null,
    }

    const parsedAdded = parseClaim(addedClaim)
    expect(parsedAdded.type).toBe('added')
    expect(parsedAdded.oldHtml).toBeNull()
    expect(parsedAdded.newHtml).toBe('<p>HTS Code: 8517.62.0050</p>')

    const removedClaim: RunClaim = {
      id: 'claim-rem',
      claim_type: 'memo_section',
      content: JSON.stringify({
        title: 'Deprecated Section',
        new_html: null,
        old_html: '<p>Old obsolete text</p>',
      }),
      status: 'approved',
      source_stage: null,
      confidence_score: null,
      original_content: null,
      review_id: null,
      created_at: null,
    }

    const parsedRemoved = parseClaim(removedClaim)
    expect(parsedRemoved.type).toBe('removed')
    expect(parsedRemoved.status).toBe('approved')
  })

  it('handles non-JSON plain text claims cleanly without hardcoding fake content', () => {
    const plainClaim: RunClaim = {
      id: 'claim-plain',
      claim_type: 'classification_code',
      content: '8517.62.0050 - Machines for the reception, conversion and transmission of data',
      status: 'rejected',
      source_stage: 'classify_product',
      confidence_score: '0.88',
      original_content: '8517.12.0000',
      review_id: null,
      created_at: null,
    }

    const parsed = parseClaim(plainClaim)
    expect(parsed.id).toBe('claim-plain')
    expect(parsed.section).toBe('Classification Code')
    expect(parsed.page).toBe('Classify Product')
    expect(parsed.type).toBe('modified')
    expect(parsed.oldHtml).toBe('8517.12.0000')
    expect(parsed.newHtml).toContain('8517.62.0050')
    expect(parsed.status).toBe('rejected')
  })
})
