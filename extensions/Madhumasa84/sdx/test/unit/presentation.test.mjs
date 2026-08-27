import assert from 'node:assert/strict';
import test from 'node:test';

import { HumanPresenter, JsonPresenter } from '../../dist/presentation/output.js';

function sink() {
  return {
    text: '',
    write(chunk) {
      this.text += chunk;
    },
  };
}

const result = {
  schemaVersion: '1.0',
  command: 'edit',
  status: 'unchanged',
  ok: true,
  session: null,
  job: null,
  document: null,
  changes: [],
  usage: null,
  timing: {
    startedAt: '2026-08-06T10:00:00.000Z',
    finishedAt: '2026-08-06T10:00:00.001Z',
    durationMs: 1,
  },
  warnings: [],
  error: null,
};

test('human output keeps results and diagnostics on separate streams', () => {
  const stdout = sink();
  const stderr = sink();
  const presenter = new HumanPresenter(stdout, stderr);

  presenter.result('No changes needed');
  presenter.diagnostic('Checking document');

  assert.equal(stdout.text, 'No changes needed\n');
  assert.equal(stderr.text, 'Checking document\n');
});

test('JSON output emits exactly one object and refuses a second result', () => {
  const stdout = sink();
  const presenter = new JsonPresenter(stdout);

  presenter.result(result);
  assert.deepEqual(JSON.parse(stdout.text), result);
  assert.equal(stdout.text.trim().split('\n').length, 1);
  assert.throws(() => presenter.result(result), /already been emitted/);
});

