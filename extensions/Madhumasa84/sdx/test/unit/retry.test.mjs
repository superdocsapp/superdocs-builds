import assert from 'node:assert/strict';
import test from 'node:test';

import { SuperDocsClient } from '../../dist/api/client.js';
import { RetryPolicy } from '../../dist/api/retry.js';

test('application 429 honors Retry-After exactly when it fits the budget', async () => {
  const delays = [];
  const policy = new RetryPolicy({ clock: () => 1_000, sleeper: async (delay) => delays.push(delay) });
  const plan = policy.responsePlan({
    status: 429, retryAfter: '2', contentType: 'application/json', safety: 'billable-write',
    attempt: 1, deadlineMs: 3_001,
  });
  assert.equal(plan.retry, true);
  assert.equal(plan.kind, 'application-429');
  assert.equal(plan.retryAfterSeconds, 2);
  await policy.wait(plan);
  assert.deepEqual(delays, [2_000]);
});

test('application 429 fails promptly when Retry-After exceeds the budget', () => {
  const policy = new RetryPolicy({ clock: () => 5_000 });
  const plan = policy.responsePlan({
    status: 429, retryAfter: '1209600', contentType: 'application/json', safety: 'read',
    attempt: 1, deadlineMs: 10_000,
  });
  assert.equal(plan.retry, false);
  assert.equal(plan.retryAfterSeconds, 1_209_600);
  assert.match(plan.reason, /exceeds available budget/);
});

test('infrastructure 429 uses deterministic bounded full jitter', () => {
  const policy = new RetryPolicy({ baseDelayMs: 100, maxDelayMs: 250, randomness: () => 0.5, clock: () => 0 });
  const delays = [1, 2, 3].map((attempt) => policy.responsePlan({
    status: 429, retryAfter: null, contentType: 'text/plain', safety: 'read', attempt, deadlineMs: 10_000,
  }).delayMs);
  assert.deepEqual(delays, [50, 100, 125]);
});

test('5xx and transport ambiguity retry only read/download operations', () => {
  const policy = new RetryPolicy({ randomness: () => 0, clock: () => 0 });
  assert.equal(policy.responsePlan({ status: 503, retryAfter: null, contentType: 'text/html', safety: 'read', attempt: 1, deadlineMs: 1_000 }).retry, true);
  assert.equal(policy.responsePlan({ status: 503, retryAfter: null, contentType: 'text/html', safety: 'billable-write', attempt: 1, deadlineMs: 1_000 }).retry, false);
  assert.equal(policy.transportPlan('signed-download', 1, 1_000).retry, true);
  assert.equal(policy.transportPlan('nonbillable-write', 1, 1_000).retry, false);
});

test('API client retries a conclusively rejected 429 with exact attempts and delay', async () => {
  let calls = 0;
  const delays = [];
  const fetcher = async () => {
    calls += 1;
    if (calls === 1) return new Response(JSON.stringify({ detail: 'mutable wording' }), {
      status: 429, headers: { 'content-type': 'application/json', 'retry-after': '3', 'x-usage-limit': '500', 'x-usage-used': '500', 'x-usage-remaining': '0' },
    });
    return Response.json({ upload_id: 'u1', upload_url: 'https://storage.test/u', expires_at: 'later', expires_in_seconds: 300, max_size_bytes: 1000, curl_example: 'redacted' });
  };
  const client = new SuperDocsClient('fixture-key', new URL('https://api.test'), fetcher, {
    clock: () => 0, sleeper: async (delay) => delays.push(delay), retryBudgetMs: 10_000,
  });
  const response = await client.requestUploadUrl('a.txt', 'text/plain', 1);
  assert.equal(response.upload_id, 'u1');
  assert.equal(calls, 2);
  assert.deepEqual(delays, [3_000]);
  assert.equal(client.usage.apiCalls, 2);
});

test('ambiguous async chat transport failure is never blindly retried', async () => {
  let calls = 0;
  const client = new SuperDocsClient('fixture-key', new URL('https://api.test'), async () => {
    calls += 1;
    throw new TypeError('connection reset');
  }, { clock: () => 0, sleeper: async () => undefined, retryBudgetMs: 10_000 });
  await assert.rejects(client.startAsyncEdit('session', 'edit'), (error) => {
    assert.equal(error.metadata.remoteState, 'unknown');
    assert.equal(error.metadata.attemptCount, 1);
    return true;
  });
  assert.equal(calls, 1);
});
