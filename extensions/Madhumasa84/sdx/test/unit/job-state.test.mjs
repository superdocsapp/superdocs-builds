import assert from 'node:assert/strict';
import test from 'node:test';

import { pollUntilAction } from '../../dist/core/job-state.js';

function job(status, overrides = {}) {
  return {
    job_id: 'job-1',
    session_id: 'session-1',
    job_type: 'chat',
    status,
    created_at: '2026-08-06T08:00:00.000Z',
    updated_at: '2026-08-06T08:00:00.000Z',
    progress: status === 'completed' ? 100 : 50,
    result: null,
    error: null,
    metadata: null,
    ...overrides,
  };
}

function sequenceClient(jobs) {
  let index = 0;
  return {
    async getJob() {
      const value = jobs[Math.min(index, jobs.length - 1)];
      index += 1;
      return value;
    },
  };
}

const options = {
  intervalMs: 1,
  timeoutMs: 1000,
  signal: undefined,
  onProgress: undefined,
};

test('polling transitions pending to in-progress to completed', async () => {
  const result = await pollUntilAction(
    sequenceClient([job('pending'), job('in_progress'), job('completed')]),
    'job-1',
    options,
  );
  assert.equal(result.kind, 'completed');
});

test('awaiting review surfaces pending changes', async () => {
  const result = await pollUntilAction(
    sequenceClient([
      job('awaiting_approval', {
        metadata: {
          awaiting_kind: 'change_review',
          pending_changes: [
            { change_id: 'change-1', operation: 'delete', chunk_id: 'chunk-1' },
          ],
        },
      }),
    ]),
    'job-1',
    options,
  );
  assert.equal(result.kind, 'approval');
  assert.equal(result.changes[0].operation, 'delete');
});

test('continue prompt branches separately from approval', async () => {
  const result = await pollUntilAction(
    sequenceClient([
      job('awaiting_approval', {
        metadata: {
          awaiting_kind: 'continue_prompt',
          continue_prompt: { message: 'Continue?', remaining: 1 },
        },
      }),
    ]),
    'job-1',
    options,
  );
  assert.equal(result.kind, 'continuation');
  assert.equal(result.prompt.message, 'Continue?');
});

for (const terminal of ['failed', 'cancelled']) {
  test(`${terminal} terminal state throws API exit 22`, async () => {
    await assert.rejects(
      pollUntilAction(
        sequenceClient([job(terminal, { error: terminal === 'failed' ? 'boom' : null })]),
        'job-1',
        options,
      ),
      (error) => error.exitCode === 22,
    );
  });
}

test('poll timeout terminates without an infinite loop', async () => {
  await assert.rejects(
    pollUntilAction(sequenceClient([job('pending')]), 'job-1', {
      ...options,
      timeoutMs: 5,
    }),
    (error) => error.exitCode === 22 && /actionable state/.test(error.message),
  );
});

test('abort signal maps to interrupted exit 130', async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    pollUntilAction(sequenceClient([job('pending')]), 'job-1', {
      ...options,
      signal: controller.signal,
    }),
    (error) => error.exitCode === 130,
  );
});

test('awaiting approval without changes is a schema mismatch', async () => {
  await assert.rejects(
    pollUntilAction(
      sequenceClient([job('awaiting_approval', { metadata: {} })]),
      'job-1',
      options,
    ),
    (error) => error.exitCode === 25,
  );
});
