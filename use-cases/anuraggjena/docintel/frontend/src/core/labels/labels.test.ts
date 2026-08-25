import { describe, it, expect } from 'vitest'
import { formatStageName } from './stages'
import { formatRunStatus, formatReviewStatus } from './statuses'
import { formatDocumentRole } from './documents'
import { formatWorkflowSlug } from './workflows'

describe('formatStageName', () => {
  it('maps known stage slugs', () => {
    expect(formatStageName('quality_gate')).toBe('Quality Check')
    expect(formatStageName('superdocs_approval')).toBe('Human Review')
  })
  it('title-cases unknown slugs', () => {
    expect(formatStageName('custom_stage_name')).toBe('Custom Stage Name')
  })
})

describe('formatRunStatus', () => {
  it('maps waiting to human label', () => {
    expect(formatRunStatus('waiting')).toBe('Waiting for review')
  })
})

describe('formatReviewStatus', () => {
  it('maps in_review', () => {
    expect(formatReviewStatus('in_review')).toBe('Needs review')
  })
})

describe('formatDocumentRole', () => {
  it('maps product_spec', () => {
    expect(formatDocumentRole('product_spec')).toBe('Product Specification')
  })
})

describe('formatWorkflowSlug', () => {
  it('maps tariff_classification', () => {
    expect(formatWorkflowSlug('tariff_classification')).toBe('Tariff Classification')
  })
})
