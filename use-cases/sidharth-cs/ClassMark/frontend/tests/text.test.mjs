import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  normalizeText,
  isNoOpChange,
  reviewActionsFor,
  countDecisions,
  explanationForDisplay,
} from '../src/lib/text.js'

test('normalizeText strips tags, line endings and collapses whitespace — case-sensitive', () => {
  assert.equal(normalizeText('<p>Hello   world</p>'), 'Hello world')
  assert.equal(normalizeText('<p>\r\nHello\r\nworld</p>'), 'Hello world')
  assert.equal(normalizeText('  <p>X</p>  '), 'X')
  // Case is preserved: a case-only edit is a meaningful change.
  assert.notEqual(normalizeText('Thier'), normalizeText('Their'))
})

test('isNoOpChange flags identical normalized text', () => {
  assert.equal(
    isNoOpChange({ old_html: '<p>The Role of Renewable Energy</p>', new_html: '<p>The Role of Renewable Energy</p>' }),
    true
  )
  assert.equal(
    isNoOpChange({ old_html: '<p>Same  words</p>', new_html: '<p>Same words</p>' }),
    true
  )
})

test('meaningful textual differences remain actionable', () => {
  assert.equal(isNoOpChange({ old_html: '<p>Thier report</p>', new_html: '<p>Their report</p>' }), false)
  assert.equal(isNoOpChange({ old_html: '<p>structures, this makes</p>', new_html: '<p>structures. This makes</p>' }), false)
  assert.equal(isNoOpChange({ old_html: '<p>cleen</p>', new_html: '<p>clean</p>' }), false)
})

test('missing text is never a no-op', () => {
  assert.equal(isNoOpChange({ old_html: '', new_html: '<p>x</p>' }), false)
  assert.equal(isNoOpChange({ old_html: null, new_html: null }), false)
})

test('formatting-only changes are flagged as no textual change (not discarded)', () => {
  assert.equal(
    isNoOpChange({ old_html: '<p>Same words</p>', new_html: '<p><strong>Same</strong> words</p>' }),
    true
  )
})

test('reviewActionsFor: no-op gets no decide controls; real change gets decide', () => {
  assert.equal(
    reviewActionsFor({ old_html: '<p>Same</p>', new_html: '<p>Same</p>' }),
    'noop'
  )
  assert.equal(
    reviewActionsFor({ old_html: '<p>Thier</p>', new_html: '<p>There</p>' }),
    'decide'
  )
})

test('countDecisions excludes no-ops from actionable counts', () => {
  const changes = [
    { old_html: '<p>Same</p>', new_html: '<p>Same</p>', decision: 'pending' }, // no-op
    { old_html: '<p>A</p>', new_html: '<p>B</p>', decision: 'approved' },
    { old_html: '<p>C</p>', new_html: '<p>D</p>', decision: 'rejected' },
    { old_html: '<p>E</p>', new_html: '<p>F</p>', decision: 'pending' },
  ]
  assert.deepEqual(countDecisions(changes), { approved: 1, rejected: 1, pending: 1, noop: 1 })
})

test('explanationForDisplay hides generic "Parallel edit" metadata', () => {
  assert.equal(
    explanationForDisplay({ ai_explanation: 'Parallel edit: Fix grammar, spelling, punctuation, and awkward structure as directed.' }),
    null
  )
  assert.equal(
    explanationForDisplay({ ai_explanation: 'parallel edit: You are a professional editor.' }),
    null
  )
})

test('explanationForDisplay keeps genuine explanations', () => {
  assert.equal(
    explanationForDisplay({ ai_explanation: 'Corrected the misspelling of "Thier".' }),
    'Corrected the misspelling of "Thier".'
  )
  assert.equal(explanationForDisplay({ ai_explanation: '' }), null)
  assert.equal(explanationForDisplay({}), null)
})

test('suggested text is never touched by the explanation filter', () => {
  const change = {
    old_html: '<p>Thier</p>',
    new_html: '<p>There</p>',
    ai_explanation: 'Parallel edit: ...',
  }
  explanationForDisplay(change) // filtering must not mutate the change
  assert.equal(change.new_html, '<p>There</p>')
})
