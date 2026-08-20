import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  HELP_TITLE,
  HELP_INTRO,
  HELP_SECTIONS,
  HELP_WORKFLOW,
  HELP_EXAMPLES_TITLE,
  HELP_EXAMPLES,
  HELP_REVIEW_TYPES_TITLE,
  HELP_REVIEW_TYPES,
  HELP_REVIEW_DEPTH_TITLE,
  HELP_REVIEW_DEPTH,
  HELP_HONESTY,
} from '../src/lib/helpContent.js'

const ALL_TEXT = [
  HELP_TITLE,
  HELP_INTRO,
  ...HELP_SECTIONS.map((s) => `${s.title} ${s.body} ${(s.bullets || []).join(' ')}`),
  ...HELP_WORKFLOW,
  HELP_EXAMPLES_TITLE,
  ...HELP_EXAMPLES,
  HELP_REVIEW_TYPES_TITLE,
  ...HELP_REVIEW_TYPES,
  HELP_REVIEW_DEPTH_TITLE,
  HELP_REVIEW_DEPTH,
  HELP_HONESTY,
].join(' ')

test('help content has the four required sections in order', () => {
  assert.deepEqual(
    HELP_SECTIONS.map((s) => s.title),
    ['SuperDocs review', 'You decide', 'After approval', 'Back to Classroom']
  )
})

test('workflow summary lists the exact chain', () => {
  assert.deepEqual(HELP_WORKFLOW, [
    'Classroom submission',
    'SuperDocs review',
    'Your approval',
    'Reviewed document',
    'Google Drive',
    'Same Classroom submission',
    'Returned to student',
  ])
})

test('teacher control and same-submission return are explicit', () => {
  assert.ok(HELP_SECTIONS[1].body.includes('you stay in control'))
  assert.ok(HELP_SECTIONS[3].body.includes('SAME Classroom submission'))
  assert.ok(HELP_SECTIONS[3].body.includes('verifies that the reviewed file remains attached'))
  assert.ok(!HELP_SECTIONS[3].body.toLowerCase().includes('email'))
  assert.ok(!HELP_SECTIONS[3].body.toLowerCase().includes('notification'))
})

test('no overpromises', () => {
  const forbidden = ['plagiarism', 'grading', 'graded', 'fact-check', 'factual', 'guarantee', 'perfectly', 'replace teacher judgment', 'grades students']
  for (const word of forbidden) {
    assert.ok(!ALL_TEXT.toLowerCase().includes(word), `forbidden claim present: ${word}`)
  }
})

test('review targets list is broad, not grammar-only', () => {
  const all = HELP_EXAMPLES.join(' ')
  for (const t of ['Grammar and spelling', 'Punctuation and sentence structure', 'Clarity, concision, and awkward wording', 'Consistency and style']) {
    assert.ok(all.includes(t), `missing review target: ${t}`)
  }
})

test('honesty line is present', () => {
  assert.equal(HELP_HONESTY, 'AI suggestions are recommendations. Review them before approving.')
})

test('help explains review types and depth without technical model names', () => {
  assert.equal(HELP_REVIEW_TYPES_TITLE, 'Review types')
  assert.equal(HELP_REVIEW_DEPTH_TITLE, 'Review depth')
  for (const type of ['Proofreading', 'Writing Quality', 'Academic Writing', 'Custom']) {
    assert.ok(HELP_REVIEW_TYPES.join(' ').includes(type))
  }
  assert.ok(HELP_REVIEW_DEPTH.includes('deeper review configuration'))
  for (const rawName of ['core', 'turbo', 'pro', 'max', 'fast', 'balanced', 'deep']) {
    assert.doesNotMatch(HELP_REVIEW_DEPTH.toLowerCase(), new RegExp(`\\b${rawName}\\b`))
  }
})
