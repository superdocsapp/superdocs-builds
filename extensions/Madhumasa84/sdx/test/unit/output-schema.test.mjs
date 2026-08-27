import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import Ajv2020 from 'ajv/dist/2020.js';

const schemaUrl = new URL('../../schemas/output-v1.schema.json', import.meta.url);
const schema = JSON.parse(await readFile(schemaUrl, 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: true });
ajv.addFormat('date-time', (value) => !Number.isNaN(Date.parse(value)));
const validate = ajv.compile(schema);

function envelope(overrides = {}) {
  return {
    schemaVersion: '1.0',
    command: 'edit',
    status: 'completed',
    ok: true,
    session: { id: 'session-1', name: 'quarterly-review' },
    job: { id: 'job-1', name: null },
    document: {
      id: 'document-1',
      name: 'report.docx',
      format: 'docx',
      path: 'report.docx',
      outputPath: 'report.edited.docx',
    },
    changes: [
      {
        id: 'change-1',
        section: 'Executive summary',
        summary: 'Tightened wording',
        before: 'Long wording',
        after: 'Clear wording',
        decision: 'approved',
      },
    ],
    usage: { apiCalls: 3, uploadedBytes: 1024, downloadedBytes: 1100 },
    timing: {
      startedAt: '2026-08-06T10:00:00.000Z',
      finishedAt: '2026-08-06T10:00:01.000Z',
      durationMs: 1000,
    },
    warnings: [],
    error: null,
    ...overrides,
  };
}

test('a representative completed result validates', () => {
  assert.equal(validate(envelope()), true, JSON.stringify(validate.errors));
});

test('an awaiting-approval result validates', () => {
  const candidate = envelope({
    status: 'awaiting_approval',
    ok: false,
    changes: [
      {
        id: 'change-1',
        section: 'Risks',
        summary: 'Updated risk wording',
        before: 'Old risk',
        after: 'Current risk',
        decision: 'pending',
      },
    ],
  });

  assert.equal(validate(candidate), true, JSON.stringify(validate.errors));
});

test('malformed and extended envelopes are rejected', () => {
  const missingCommand = envelope();
  delete missingCommand.command;
  assert.equal(validate(missingCommand), false);

  assert.equal(validate(envelope({ accidental: 'unstable' })), false);
});


test('Stage 3 data, diagnostics, and document change ID are backward-compatible additions', () => {
  const candidate = envelope({
    data: { activeProfile: 'work' },
    diagnostics: [{ name: 'node', status: 'pass', message: 'Node is supported.' }],
    changes: [{
      id: 'change-1', documentId: 'document-1', section: 'Risks', summary: 'Updated',
      before: 'Old', after: 'New', decision: 'pending',
    }],
  });
  assert.equal(validate(candidate), true, JSON.stringify(validate.errors));
});

test('Stage 4 retry and unknown-state metadata remains valid inside v1 error details', () => {
  const candidate = envelope({
    status: 'failed', ok: false,
    error: {
      code: 'SDX_22', message: 'Remote outcome is unknown.',
      details: {
        httpStatus: 429, retryable: false, retryAfterSeconds: 60,
        attemptCount: 1, retryKind: 'application-429', remoteState: 'unknown',
        operationId: '00000000-0000-4000-8000-000000000001',
      },
    },
  });
  assert.equal(validate(candidate), true, JSON.stringify(validate.errors));
});
