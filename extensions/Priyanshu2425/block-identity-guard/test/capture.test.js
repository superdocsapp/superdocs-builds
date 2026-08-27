import { test } from 'node:test';
import assert from 'node:assert/strict';

import { extractDocumentHtml } from '../src/capture.js';

const SSE = [
  'event: intermediate',
  'data: {"type":"intermediate","status":"reading the document"}',
  '',
  ': keep-alive',
  '',
  'event: document_sync',
  'data: {"type":"document_sync","content":"<p data-chunk-id=\\"a\\">Section 1</p>","focused_document_id":"d1"}',
  '',
  'event: final',
  'data: {"type":"final","updated_html":"<p data-chunk-id=\\"a\\">Section 1, edited</p>"}',
  '',
].join('\n');

test('reads the prepared HTML out of a saved SSE stream', () => {
  const result = extractDocumentHtml(SSE);
  assert.equal(result.html, '<p data-chunk-id="a">Section 1</p>');
  assert.equal(result.documentId, 'd1');
  assert.equal(result.source, 'document_sync');
});

test('can read the final document instead, for an after-side capture', () => {
  const result = extractDocumentHtml(SSE, { event: 'final' });
  assert.match(result.html, /Section 1, edited/);
});

test('reads a single event posted as JSON', () => {
  const result = extractDocumentHtml(JSON.stringify({
    type: 'document_sync',
    content: '<p data-chunk-id="a">One</p>',
  }));
  assert.equal(result.html, '<p data-chunk-id="a">One</p>');
});

test('reads a chat response body', () => {
  const result = extractDocumentHtml(JSON.stringify({
    session_id: 's1',
    updated_html: '<p data-chunk-id="a">One</p>',
  }));
  assert.equal(result.html, '<p data-chunk-id="a">One</p>');
});

test('picks the document asked for in a multi-document session', () => {
  const payload = JSON.stringify([
    { type: 'document_sync', content: '<p data-chunk-id="a">Contract</p>', focused_document_id: 'd1' },
    { type: 'document_sync', content: '<p data-chunk-id="b">Invoice</p>', focused_document_id: 'd2' },
  ]);
  assert.match(extractDocumentHtml(payload, { documentId: 'd2' }).html, /Invoice/);
  assert.match(extractDocumentHtml(payload, { documentId: 'd1' }).html, /Contract/);
});

test('the last sync in a stream wins, because it is the newest', () => {
  const stream = [
    'event: document_sync',
    'data: {"type":"document_sync","content":"<p data-chunk-id=\\"a\\">first</p>"}',
    '',
    'event: document_sync',
    'data: {"type":"document_sync","content":"<p data-chunk-id=\\"a\\">second</p>"}',
    '',
  ].join('\n');
  assert.match(extractDocumentHtml(stream).html, /second/);
  assert.equal(extractDocumentHtml(stream).candidates, 2);
});

test('an unusable payload explains what was expected', () => {
  assert.throws(() => extractDocumentHtml('nothing useful here'), /document_sync/);
  assert.throws(() => extractDocumentHtml('{"broken":'), /neither an SSE stream nor valid JSON/);
});

test('malformed data lines are skipped rather than crashing the capture', () => {
  const stream = [
    'event: document_sync',
    'data: {not json}',
    '',
    'event: document_sync',
    'data: {"type":"document_sync","content":"<p data-chunk-id=\\"a\\">ok</p>"}',
    '',
  ].join('\n');
  assert.match(extractDocumentHtml(stream).html, /ok/);
});
