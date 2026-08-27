import assert from 'node:assert/strict';
import test from 'node:test';

import {
  redactRecord,
  redactText,
  redactUnknown,
  redactUrl,
} from '../../dist/security/redaction.js';

test('signed URL query parameters are removed', () => {
  const redacted = redactUrl('https://storage.example/file?signature=secret&token=other');
  assert.doesNotMatch(redacted, /secret|token=other/);
  assert.match(redacted, /REDACTED|%5BREDACTED%5D/);
});

test('bearer and API-key text is redacted', () => {
  assert.equal(
    redactText('Authorization: Bearer sk_fixture_secret'),
    'Authorization: [REDACTED]',
  );
});

test('nested sensitive fields are redacted recursively', () => {
  assert.deepEqual(
    redactUnknown({ nested: { api_key: 'secret', safe: 'value' } }),
    { nested: { api_key: '[REDACTED]', safe: 'value' } },
  );
});

test('record redaction preserves safe server details', () => {
  assert.deepEqual(
    redactRecord({ authorization: 'secret', request_id: 'request-1' }),
    { authorization: '[REDACTED]', request_id: 'request-1' },
  );
});
