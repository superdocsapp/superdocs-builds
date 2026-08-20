import { test } from 'node:test'
import assert from 'node:assert/strict'
import { errorMessage, ApiError } from '../src/api.js'

test('FastAPI validation detail array renders as a message, never [object Object]', () => {
  const msg = errorMessage({ status: 422 }, {
    detail: [{ loc: ['body'], msg: 'Field required', type: 'missing' }],
  })
  assert.equal(msg, 'Field required')
  assert.ok(!msg.includes('[object Object]'))
})

test('string detail passes through', () => {
  assert.equal(errorMessage({ status: 409 }, { detail: 'export must complete first' }), 'export must complete first')
})

test('403 gets an actionable Classroom explanation', () => {
  const msg = errorMessage({ status: 403 }, {})
  assert.ok(msg.includes('assignment was created outside'))
})

test('object detail is JSON-serialized, not stringified as [object Object]', () => {
  const msg = errorMessage({ status: 500 }, { detail: { reason: 'boom' } })
  assert.ok(msg.includes('boom'))
  assert.ok(!msg.includes('[object Object]'))
})

test('fallback includes status', () => {
  assert.equal(errorMessage({ status: 404 }, {}), 'Request failed (404)')
})

test('ApiError carries status and detail', () => {
  const e = new ApiError('msg', 422, [{ msg: 'x' }])
  assert.equal(e.status, 422)
  assert.deepEqual(e.detail, [{ msg: 'x' }])
})
