import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('UI contains the readiness journey and item-level decisions', async () => {
  const source = await readFile(new URL('../src/App.jsx', import.meta.url), 'utf8')
  assert.match(source, /Submit item decisions/)
  assert.match(source, /citations/)
  assert.match(source, /current_stage/)
})
