import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';

import {
  assertRecordingAuthorized, createRecordingFetch, readCassette,
  SanitizedCassetteRecorder, startReplayServer, validateCassetteSafe,
} from '../recording/cassette.mjs';

const contractCassettePath = new URL('../fixtures/cassettes/contract-derived-stage4.json', import.meta.url).pathname;

test('recording requires both explicit flag and environment credential without exposing it', () => {
  assert.throws(() => assertRecordingAuthorized({}), /explicit SDX_RECORD_FIXTURE=1/);
  assert.throws(() => assertRecordingAuthorized({ SDX_RECORD_FIXTURE: '1' }), /SUPERDOCS_API_KEY/);
  assert.doesNotThrow(() => assertRecordingAuthorized({ SDX_RECORD_FIXTURE: '1', SUPERDOCS_API_KEY: 'not-printed' }));
});

test('recorder sanitizes API interactions, excludes signed storage, and caps billable edits', async () => {
  const recorder = new SanitizedCassetteRecorder();
  const calls = [];
  const recordingFetch = createRecordingFetch({
    apiBaseUrl: 'https://api.example.test', recorder,
    realFetch: async (input, init) => {
      calls.push(String(input));
      return new Response(JSON.stringify({
        job_id: 'real-job-987', session_id: 'real-session-654', created_at: '2026-08-06T00:00:00Z',
        download_url: 'https://storage.example.test/private?X-Amz-Signature=secret', usage: { used: 12, remaining: 3 },
      }), { status: 200, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer response-secret' } });
    },
  });
  await recordingFetch('https://api.example.test/v1/chat/async', {
    method: 'POST', headers: { Authorization: 'Bearer request-secret' },
    body: JSON.stringify({ session_id: 'real-session-654', message: 'synthetic disposable instruction' }),
  });
  await recordingFetch('https://storage.example.test/private?X-Amz-Signature=secret', { method: 'PUT', body: Buffer.from('document bytes') });
  const cassette = recorder.cassette();
  assert.equal(calls.length, 2); assert.equal(cassette.interactions.length, 1);
  const serialized = JSON.stringify(cassette);
  assert.doesNotMatch(serialized, /request-secret|response-secret|X-Amz-Signature|real-job|real-session|synthetic disposable instruction|document bytes/);
  assert.equal(cassette.interactions[0].response.body.download_url, '<signed-url>');
  await assert.rejects(() => recordingFetch('https://api.example.test/v1/chat/async', { method: 'POST', body: '{}' }), /cap exceeded/);
});

test('unsafe cassette validation rejects credentials and signed queries', () => {
  const base = { schemaVersion: 1, interactions: [{ request: { method: 'GET', path: '/v1/jobs' }, response: { status: 200, headers: {}, body: null } }] };
  assert.throws(() => validateCassetteSafe({ ...base, leaked: 'Bearer abcdefghijklmnop' }), /credential or signed query/);
  assert.throws(() => validateCassetteSafe({ ...base, leaked: 'https://x.test/a?X-Amz-Signature=secret' }), /credential or signed query/);
});

test('sanitized cassette writes atomically with 0600 permissions', async () => {
  const directory = await mkdtemp('/tmp/sdx-stage4-cassette-');
  try {
    const path = join(directory, 'safe.json'); const recorder = new SanitizedCassetteRecorder({ provenance: 'offline test' });
    await recorder.capture({ method: 'GET', url: 'https://api.example.test/v1/jobs', response: new Response('{}', { headers: { 'Content-Type': 'application/json' } }) });
    await recorder.write(path);
    assert.equal((await stat(path)).mode & 0o777, 0o600); assert.equal((await readCassette(path)).interactions.length, 1);
    assert.doesNotMatch(await readFile(path, 'utf8'), /authorization/i);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('contract-derived replay runs locally without a credential or external network', async () => {
  const cassette = await readCassette(contractCassettePath);
  assert.match(cassette.provenance, /not live-recorded/);
  const replay = await startReplayServer(cassette);
  try {
    const first = await fetch(`${replay.baseUrl}/v1/chat/async`, { method: 'POST', body: '{}' });
    assert.equal((await first.json()).status, 'pending');
    const second = await fetch(`${replay.baseUrl}/v1/jobs/%3Cjob-1%3E`); assert.equal((await second.json()).status, 'pending');
    const third = await fetch(`${replay.baseUrl}/v1/jobs/%3Cjob-1%3E`); assert.equal((await third.json()).status, 'awaiting_approval');
    assert.equal(replay.consumed(), 3);
  } finally { await replay.close(); }
});
