import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

// The header renders in the browser; without a DOM test harness we assert
// on the component source — the regressions this guards are structural:
// exactly one Help trigger, exactly one Sign out, and NO avatar circle
// (the "?"/"T" lookalike controls that appeared next to Help).
const header = readFileSync(new URL('../src/components/AppHeader.jsx', import.meta.url), 'utf8')

test('exactly one Help/About trigger exists in the header', () => {
  const count = (header.match(/className="help-button"/g) || []).length
  assert.equal(count, 1)
  assert.ok(header.includes('aria-label="Help and workflow information"'))
  assert.ok(header.includes('aria-haspopup="dialog"'))
})

test('no avatar circle / "T" or "?" initial control exists', () => {
  assert.ok(!header.includes('avatar'))
  assert.ok(!header.includes("'T'"))
  assert.ok(!header.includes("'?'"))
  assert.ok(!header.includes('initial'))
})

test('sign out appears exactly once and stays separate', () => {
  assert.equal((header.match(/Sign out/g) || []).length, 1)
  assert.equal((header.match(/className="btn btn-ghost btn-sm"/g) || []).length, 1)
})

test('Help and Sign out are distinct buttons', () => {
  const helpIdx = header.indexOf('help-button')
  const signoutIdx = header.indexOf('Sign out')
  assert.ok(helpIdx > -1 && signoutIdx > -1)
  assert.ok(helpIdx !== signoutIdx)
})
