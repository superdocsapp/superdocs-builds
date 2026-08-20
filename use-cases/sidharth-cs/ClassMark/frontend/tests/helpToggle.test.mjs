import { test } from 'node:test'
import assert from 'node:assert/strict'
import { helpToggle, INITIAL_HELP_STATE } from '../src/lib/helpToggle.js'

// The exact sequence required by the bug report, driven through the
// reducer the header actually uses.
test('toggle sequence: open, close on same button, reopen, close outside, close on escape', () => {
  let s = helpToggle(INITIAL_HELP_STATE, { type: 'button-click' })
  assert.equal(s.open, true) // first click opens

  s = helpToggle(s, { type: 'button-click' })
  assert.equal(s.open, false) // second click on the SAME button closes

  s = helpToggle(s, { type: 'button-click' })
  assert.equal(s.open, true) // reopen

  s = helpToggle(s, { type: 'outside-pointerdown' })
  assert.equal(s.open, false) // outside click closes

  s = helpToggle(s, { type: 'button-click' })
  assert.equal(s.open, true) // reopen after outside close

  s = helpToggle(s, { type: 'escape' })
  assert.equal(s.open, false) // Escape closes
})

test('outside click and escape never reopen when already closed', () => {
  let s = helpToggle(INITIAL_HELP_STATE, { type: 'outside-pointerdown' })
  assert.equal(s.open, false) // ignored while closed
  s = helpToggle(INITIAL_HELP_STATE, { type: 'escape' })
  assert.equal(s.open, false) // ignored while closed
})

test('only the button click toggles open; everything else only closes', () => {
  const s = helpToggle({ open: false }, { type: 'button-click' })
  assert.equal(s.open, true)
  for (const t of ['outside-pointerdown', 'escape']) {
    assert.equal(helpToggle({ open: true }, { type: t }).open, false)
    assert.equal(helpToggle({ open: false }, { type: t }).open, false)
  }
})
