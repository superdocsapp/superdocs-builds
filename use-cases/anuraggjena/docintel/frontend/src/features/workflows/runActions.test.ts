import { describe, it, expect } from 'vitest'
import { getRunActions } from './runActions'

describe('getRunActions', () => {
  it('shows kill for running', () => {
    expect(getRunActions({ status: 'running', review_id: null, workflow_slug: 'tariff_classification' }))
      .toContain('kill')
  })
  it('shows openReview for waiting with review_id on tariff', () => {
    expect(getRunActions({ status: 'waiting', review_id: 'r1', workflow_slug: 'tariff_classification' }))
      .toContain('openReview')
  })
  it('shows screenplayReview for waiting screenplay', () => {
    expect(getRunActions({ status: 'waiting', review_id: null, workflow_slug: 'screenplay' }))
      .toContain('screenplayReview')
  })
  it('shows resume for blocked with checkpoint (resumable=true)', () => {
    const actions = getRunActions({ status: 'blocked', resumable: true, review_id: null, workflow_slug: 'tariff_classification' })
    expect(actions).toContain('resume')
    expect(actions).not.toContain('replay')
  })
  it('shows replay for blocked without checkpoint (resumable=false)', () => {
    const actions = getRunActions({ status: 'blocked', resumable: false, review_id: null, workflow_slug: 'tariff_classification' })
    expect(actions).toContain('replay')
    expect(actions).not.toContain('resume')
  })
  it('shows resume for cancelled with checkpoint (resumable=true)', () => {
    const actions = getRunActions({ status: 'cancelled', resumable: true, review_id: null, workflow_slug: 'tariff_classification' })
    expect(actions).toContain('resume')
    expect(actions).not.toContain('replay')
  })
  it('shows replay for cancelled without checkpoint (resumable=false)', () => {
    const actions = getRunActions({ status: 'cancelled', resumable: false, review_id: null, workflow_slug: 'tariff_classification' })
    expect(actions).toContain('replay')
    expect(actions).not.toContain('resume')
  })
  it('shows resume for interrupted/failed with checkpoint (resumable=true)', () => {
    const actions = getRunActions({ status: 'failed', resumable: true, review_id: null, workflow_slug: 'tariff_classification' })
    expect(actions).toContain('resume')
    expect(actions).not.toContain('replay')
  })
  it('shows replay for failed without checkpoint (resumable=false)', () => {
    const actions = getRunActions({ status: 'failed', resumable: false, review_id: null, workflow_slug: 'tariff_classification' })
    expect(actions).toContain('replay')
    expect(actions).not.toContain('resume')
  })
  it('shows lineage and replay for completed (never resume)', () => {
    const actions = getRunActions({ status: 'completed', resumable: false, review_id: 'r1', workflow_slug: 'tariff_classification' })
    expect(actions).toContain('lineage')
    expect(actions).toContain('replay')
    expect(actions).toContain('openReview')
    expect(actions).not.toContain('resume')
  })
})
