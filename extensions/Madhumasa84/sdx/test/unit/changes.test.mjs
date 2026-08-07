import assert from 'node:assert/strict';
import test from 'node:test';

import {
  normalizeContinuePrompt,
  normalizePendingChanges,
} from '../../dist/core/changes.js';

const change = {
  change_id: 'change-1',
  operation: 'edit',
  chunk_id: 'chunk-1',
  old_html: '<p>Old</p>',
  new_html: '<p>New</p>',
  ai_explanation: 'Clearer wording',
};

test('normal pending-change object preserves all documented fields', () => {
  const [normalized] = normalizePendingChanges([change]);
  assert.deepEqual(normalized, {
    id: 'change-1',
    operation: 'edit',
    chunkId: 'chunk-1',
    documentId: null,
    oldContent: '<p>Old</p>',
    newContent: '<p>New</p>',
    explanation: 'Clearer wording',
  });
});

test('JSON-encoded pending change receives a second parse', () => {
  const [normalized] = normalizePendingChanges([JSON.stringify(change)]);
  assert.equal(normalized.id, 'change-1');
});

test('encoded proposed-change batch content is flattened', () => {
  const normalized = normalizePendingChanges({
    content: JSON.stringify({ changes: [change, { ...change, change_id: 'change-2' }] }),
  });
  assert.deepEqual(
    normalized.map(({ id }) => id),
    ['change-1', 'change-2'],
  );
});

test('malformed encoded pending change maps to schema exit 25', () => {
  assert.throws(
    () => normalizePendingChanges(['{"change_id":']),
    (error) => error.exitCode === 25,
  );
});

test('missing required change fields cannot become empty success', () => {
  assert.throws(
    () => normalizePendingChanges([{ operation: 'edit' }]),
    (error) => error.exitCode === 25,
  );
});

test('empty pending collection is rejected', () => {
  assert.throws(
    () => normalizePendingChanges([]),
    (error) => error.exitCode === 25,
  );
});

test('JSON-encoded continuation prompt is normalized', () => {
  assert.deepEqual(
    normalizeContinuePrompt(
      JSON.stringify({ message: 'Continue?', done: 2, total: 3, remaining: 1 }),
    ),
    { message: 'Continue?', done: 2, total: 3, remaining: 1 },
  );
});
