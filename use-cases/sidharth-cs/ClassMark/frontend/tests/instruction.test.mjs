import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  DEFAULT_REVIEW_DEPTH,
  DEFAULT_REVIEW_MODE,
  REVIEW_DEPTHS,
  REVIEW_MODES,
  isCustomReview,
} from '../src/lib/reviewConfig.js'
import { readFileSync } from 'node:fs'

const reviewPanel = readFileSync(new URL('../src/components/ReviewInstruction.jsx', import.meta.url), 'utf8')

test('default review configuration is Proofreading and Standard', () => {
  assert.equal(DEFAULT_REVIEW_MODE, 'proofreading')
  assert.equal(DEFAULT_REVIEW_DEPTH, 'standard')
})

test('all teacher-facing modes and depths are available', () => {
  assert.deepEqual(REVIEW_MODES.map((option) => option.value), [
    'proofreading', 'writing_quality', 'academic_writing', 'custom',
  ])
  assert.deepEqual(REVIEW_DEPTHS.map((option) => option.value), [
    'quick', 'standard', 'thorough',
  ])
})

test('Custom requires teacher instructions while other modes do not', () => {
  assert.equal(isCustomReview('custom'), true)
  assert.equal(isCustomReview('proofreading'), false)
  assert.ok(reviewPanel.includes('customMissingInstruction'))
  assert.ok(reviewPanel.includes('required={custom}'))
})

test('teacher UI never exposes raw SuperDocs model or thinking names', () => {
  const renderedLabels = [...REVIEW_MODES, ...REVIEW_DEPTHS]
    .map((option) => `${option.label} ${option.description}`)
    .join(' ')
    .toLowerCase()
  for (const rawName of ['core', 'turbo', 'pro', 'max', 'fast', 'balanced', 'deep']) {
    assert.ok(!reviewPanel.includes(rawName), `${rawName} leaked into review UI`)
    assert.doesNotMatch(renderedLabels, new RegExp(`\\b${rawName}\\b`))
  }
  assert.ok(!reviewPanel.includes('model_tier'))
  assert.ok(!reviewPanel.includes('thinking_depth'))
})
