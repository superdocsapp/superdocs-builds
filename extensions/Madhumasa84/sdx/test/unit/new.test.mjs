import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import test from 'node:test';

import { createDocument } from '../../dist/commands/new.js';
import { safeTitleSlug } from '../../dist/commands/workflow.js';

test('new refuses terminal stdin instead of waiting forever', async () => {
  await assert.rejects(
    createDocument(
      { title: 'TTY input', format: 'docx', overwrite: false },
      {
        client: {}, sessions: {}, jobs: {}, input: Readable.from([]), inputIsTTY: true,
        diagnostic() {},
      },
    ),
    (error) => error.exitCode === 10 && /stdin is a terminal/.test(error.message),
  );
});

test('title-to-filename conversion prevents traversal and is predictable', () => {
  assert.equal(safeTitleSlug('Q3 Review'), 'q3-review');
  assert.equal(safeTitleSlug('../../Quarter: Review?'), 'quarter-review');
  assert.throws(() => safeTitleSlug('../..'), /usable filename/);
});
