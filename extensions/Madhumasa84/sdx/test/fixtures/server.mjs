import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { once } from 'node:events';

import { createFixtureExport } from './export-artifacts.mjs';

const NOW = '2026-08-06T08:00:00.000Z';

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function json(response, status, body, headers = {}) {
  response.writeHead(status, {
    'Content-Type': 'application/json',
    'X-Request-Id': 'fixture-request-id',
    ...headers,
  });
  response.end(JSON.stringify(body));
}

function jobBody(state, status, extra = {}) {
  return {
    job_id: 'job-1',
    session_id: state.sessionId,
    job_type: 'chat',
    status,
    created_at: NOW,
    updated_at: NOW,
    progress:
      status === 'pending'
        ? 5
        : status === 'in_progress'
          ? 50
          : status === 'completed'
            ? 100
            : 75,
    result: null,
    error: null,
    metadata: null,
    ...extra,
  };
}

export async function startFixtureServer(options = {}) {
  const expectedKey = options.expectedKey ?? 'fixture-api-key';
  const mode = options.mode ?? 'normal';
  const streamingUpload = options.streamingUpload === true;
  const downloadBytes = options.downloadBytes;
  const observations = {
    apiRequests: [],
    uploadCalls: 0,
    signedUploadCalls: 0,
    editCalls: 0,
    jobCalls: 0,
    signedUploadAuthorization: undefined,
    signedDownloadAuthorization: undefined,
    uploadRequest: undefined,
    uploadedBytes: Buffer.alloc(0),
    uploadedByteCount: 0,
    uploadedSha256: null,
    uploadChunkCount: 0,
    maxUploadChunkBytes: 0,
    processRequest: undefined,
    editRequest: undefined,
    jobStatuses: [],
    approvalRequest: undefined,
    approvalCalls: 0,
    continuationRequest: undefined,
    continuationCalls: 0,
    downloadRequest: undefined,
    downloadCalls: 0,
    signedDownloadCalls: 0,
  };
  const state = {
    baseUrl: '',
    sessionId: 'fixture-session',
    scenario: mode,
    pollCount: 0,
    approvalSubmitted: false,
    continuationSubmitted: false,
  };

  const server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? '/', state.baseUrl);
      const isStorage = url.pathname.startsWith('/storage/');
      if (!isStorage) {
        observations.apiRequests.push({
          method: request.method,
          path: url.pathname,
          authorization: request.headers.authorization,
        });
        if (request.headers.authorization !== `Bearer ${expectedKey}`) {
          json(response, 401, { detail: 'Invalid API key' });
          return;
        }
      }

      if (request.method === 'POST' && url.pathname === '/v1/uploads') {
        observations.uploadCalls += 1;
        observations.uploadRequest = JSON.parse((await readBody(request)).toString('utf8'));
        if (mode === 'application-429-short' && observations.uploadCalls === 1) {
          json(response, 429, { detail: 'fixture cooldown wording' }, {
            'Retry-After': '0', 'X-Usage-Limit': '500', 'X-Usage-Used': '499', 'X-Usage-Remaining': '1',
          });
          return;
        }
        if (mode === 'application-429-long') {
          json(response, 429, { detail: 'fixture quota wording' }, {
            'Retry-After': '1209600', 'X-Usage-Limit': '500', 'X-Usage-Used': '500', 'X-Usage-Remaining': '0',
          });
          return;
        }
        if (mode === 'infrastructure-429' && observations.uploadCalls < 3) {
          response.writeHead(429, { 'Content-Type': 'text/plain' });
          response.end('Rate exceeded');
          return;
        }
        json(response, 200, {
          upload_id: 'upload-1',
          upload_url: `${state.baseUrl}storage/upload?X-Amz-Signature=fixture-secret`,
          expires_at: NOW,
          expires_in_seconds: 300,
          max_size_bytes: 104857600,
          curl_example: 'sanitized fixture command',
        });
        return;
      }

      if (request.method === 'PUT' && url.pathname === '/storage/upload') {
        observations.signedUploadCalls += 1;
        observations.signedUploadAuthorization = request.headers.authorization;
        if (state.scenario === 'signed-upload-drop') {
          for await (const chunk of request) {
            observations.uploadedByteCount += Buffer.byteLength(chunk);
            request.socket.destroy();
            return;
          }
        }
        if (streamingUpload) {
          const hash = createHash('sha256'); let count = 0;
          for await (const chunk of request) {
            const bytes = Buffer.from(chunk); count += bytes.length; hash.update(bytes);
            observations.uploadChunkCount += 1;
            observations.maxUploadChunkBytes = Math.max(observations.maxUploadChunkBytes, bytes.length);
          }
          observations.uploadedByteCount = count;
          observations.uploadedSha256 = hash.digest('hex');
          observations.uploadedBytes = Buffer.alloc(0);
        } else {
          observations.uploadedBytes = await readBody(request);
          observations.uploadedByteCount = observations.uploadedBytes.length;
          observations.uploadedSha256 = createHash('sha256').update(observations.uploadedBytes).digest('hex');
          observations.uploadChunkCount = observations.uploadedBytes.length > 0 ? 1 : 0;
          observations.maxUploadChunkBytes = observations.uploadedBytes.length;
        }
        if (mode === 'signed-upload-error') {
          response.writeHead(403, { 'Content-Type': 'text/plain' });
          response.end(`expired ${url.toString()}`);
          return;
        }
        response.writeHead(200);
        response.end();
        return;
      }

      if (
        request.method === 'POST' &&
        url.pathname === '/v1/uploads/upload-1/process'
      ) {
        observations.processRequest = JSON.parse((await readBody(request)).toString('utf8'));
        if (mode === 'parse-mismatch') {
          json(response, 200, { status: 'parsed' });
          return;
        }
        state.sessionId = observations.processRequest.session_id;
        json(response, 200, {
          html: null,
          session_id: state.sessionId,
          filename: observations.processRequest.filename,
          chunks_count: 2,
          version_id: 'version-1',
          document_id: 'doc-primary',
          durable_document_id: 'durable-doc-1',
          status: 'processed',
          parse_mode: 'document',
          warnings: null,
        });
        return;
      }

      if (request.method === 'POST' && url.pathname === '/v1/chat/async') {
        if (mode === 'drop-before-chat-accept') {
          request.socket.destroy();
          return;
        }
        observations.editCalls += 1;
        state.pollCount = 0;
        state.approvalSubmitted = false;
        state.continuationSubmitted = false;
        observations.editRequest = JSON.parse((await readBody(request)).toString('utf8'));
        state.sessionId = observations.editRequest.session_id;
        if (mode === 'drop-after-chat-accept') {
          response.destroy();
          return;
        }
        const message = observations.editRequest.message;
        state.scenario = message.includes('continue')
          ? 'continue'
          : message.includes('malformed')
            ? 'malformed'
            : message.includes('already satisfied')
              ? 'unchanged'
              : message.includes('fail job')
                ? 'failed'
                : message.includes('cancel job')
                  ? 'cancelled'
                  : message.includes('unsafe diff')
                    ? 'unsafe diff'
                    : mode;
        json(response, 200, {
          job_id: 'job-1',
          session_id: state.sessionId,
          status: 'pending',
          message: 'queued',
        });
        return;
      }

      if (request.method === 'GET' && url.pathname === '/v1/jobs/job-1') {
        observations.jobCalls += 1;
        if (state.scenario === 'expired-job') {
          json(response, 404, { detail: 'Job not found' });
          return;
        }
        const transientStatus = /^transient-(500|502|503)$/.exec(mode)?.[1];
        if (transientStatus && observations.jobCalls < 3) {
          response.writeHead(Number(transientStatus), { 'Content-Type': 'text/html' });
          response.end('<html>gateway unavailable</html>');
          return;
        }
        if (mode === 'html-gateway-504') {
          response.writeHead(504, { 'Content-Type': 'text/html' });
          response.end('<html><title>Gateway timeout</title></html>');
          return;
        }
        if (mode === 'malformed-job-json') {
          response.writeHead(200, { 'Content-Type': 'application/json' }); response.end('{'); return;
        }
        if (mode === 'partial-job-body') {
          response.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': '1000' });
          response.write('{"job_id":'); setImmediate(() => response.destroy()); return;
        }
        if (state.scenario === 'unsafe-completed') {
          json(response, 200, jobBody(state, 'completed', { result: {
            response: 'unexpected application', session_id: state.sessionId,
            document_changes: { updated_html: '<p>Unsafe</p>', version_id: 'version-unsafe', changes_summary: 'Unsafe', changes: [{ change_id: 'unsafe-change' }], chunk_diffs: [] },
            usage: { monthly_used: 1, monthly_remaining: 499 },
          } }));
          return;
        }
        if (mode === 'approve-completed') { json(response, 200, jobBody(state, 'completed')); return; }
        if (mode === 'approve-failed') { json(response, 200, jobBody(state, 'failed', { error: 'fixture failure' })); return; }
        if (mode === 'approve-cancelled') { json(response, 200, jobBody(state, 'cancelled')); return; }
        if (mode === 'approve-continuation') {
          json(response, 200, jobBody(state, 'awaiting_approval', { metadata: { awaiting_kind: 'continue_prompt', continue_prompt: { message: 'Continue?' } } }));
          return;
        }
        state.pollCount += 1;
        if (state.scenario === 'stuck') {
          observations.jobStatuses.push('pending');
          json(response, 200, jobBody(state, 'pending'));
          return;
        }
        if (state.pollCount === 1) {
          observations.jobStatuses.push('pending');
          json(response, 200, jobBody(state, 'pending'));
          return;
        }
        if (state.pollCount === 2) {
          observations.jobStatuses.push('in_progress');
          json(response, 200, jobBody(state, 'in_progress'));
          return;
        }
        if (state.scenario === 'failed') {
          observations.jobStatuses.push('failed');
          json(response, 200, jobBody(state, 'failed', { error: 'fixture failure' }));
          return;
        }
        if (state.scenario === 'cancelled') {
          observations.jobStatuses.push('cancelled');
          json(response, 200, jobBody(state, 'cancelled'));
          return;
        }
        if (state.scenario === 'unchanged') {
          observations.jobStatuses.push('completed');
          json(
            response,
            200,
            jobBody(state, 'completed', {
              result: {
                response: 'Already satisfied',
                session_id: state.sessionId,
                document_changes: {
                  updated_html: '<p data-chunk-id="chunk-1">Already clear</p>',
                  version_id: 'version-1',
                  changes_summary: 'No changes needed',
                  changes: [],
                  chunk_diffs: [],
                },
                usage: { monthly_used: 1, monthly_remaining: 499 },
              },
            }),
          );
          return;
        }
        if (state.scenario === 'repeated-hitl' && observations.approvalCalls === 1) {
          observations.jobStatuses.push('awaiting_approval');
          json(response, 200, jobBody(state, 'awaiting_approval', { metadata: {
            awaiting_kind: 'change_review', pending_changes: [{
              change_id: 'change-round-2', operation: 'edit', chunk_id: 'chunk-round-2',
              old_html: '<p>Round one</p>', new_html: '<p>Round two</p>', ai_explanation: 'Second explicit review round',
            }],
          } }));
          return;
        }
        if (state.scenario === 'repeated-continuation' && observations.continuationCalls < 2) {
          observations.jobStatuses.push('awaiting_approval');
          json(response, 200, jobBody(state, 'awaiting_approval', { metadata: {
            awaiting_kind: 'continue_prompt', continue_prompt: {
              message: `Continue synthetic round ${observations.continuationCalls + 1}?`,
              done: observations.continuationCalls, total: 2, remaining: 2 - observations.continuationCalls,
            },
          } }));
          return;
        }
        if (state.approvalSubmitted || state.continuationSubmitted) {
          observations.jobStatuses.push('completed');
          const applied =
            observations.approvalRequest?.changes?.filter((item) => item.approved) ?? [
              { change_id: 'continued-change' },
            ];
          json(
            response,
            200,
            jobBody(state, 'completed', {
              result: {
                response: 'Edit complete',
                session_id: state.sessionId,
                document_changes: {
                  updated_html: '<p data-chunk-id="chunk-1">Updated</p>',
                  version_id: 'version-2',
                  changes_summary: 'Updated fixture document',
                  changes: applied,
                },
                usage: { monthly_used: 2, monthly_remaining: 498 },
              },
            }),
          );
          return;
        }
        observations.jobStatuses.push('awaiting_approval');
        if (state.scenario === 'continue') {
          json(
            response,
            200,
            jobBody(state, 'awaiting_approval', {
              metadata: {
                awaiting_kind: 'continue_prompt',
                continue_prompt: JSON.stringify({
                  message: 'One section remains. Continue?',
                  done: 1,
                  total: 2,
                  remaining: 1,
                }),
              },
            }),
          );
          return;
        }
        const unsafeDiff = state.scenario === 'unsafe diff';
        const first = {
          change_id: 'change-1',
          operation: 'edit',
          chunk_id: 'chunk-1',
          document_id: 'durable-doc-1',
          old_html: unsafeDiff ? '<h2>Risks</h2><p>Old paragraph.</p><ul><li>First</li><li>Second</li></ul><p>\u001b[31mhostile</p>' : '<p>Long summary</p>',
          new_html: unsafeDiff ? `<h2>Risks</h2><p>${'Updated '.repeat(900)}</p>` : '<p>Clear summary</p>',
          ai_explanation: unsafeDiff ? '\u001b]0;owned\u0007Clarified risks' : 'Tightened the summary',
        };
        const second = {
          change_id: 'change-2',
          operation: 'create',
          chunk_id: 'chunk-2',
          old_html: null,
          new_html: '<p>New detail</p>',
          ai_explanation: 'Added supporting detail',
        };
        json(
          response,
          200,
          jobBody(state, 'awaiting_approval', {
            metadata: {
              awaiting_kind: 'change_review',
              pending_changes:
                state.scenario === 'malformed'
                  ? ['{"change_id":']
                  : [first, JSON.stringify(second)],
            },
          }),
        );
        return;
      }

      if (
        request.method === 'POST' &&
        url.pathname === `/v1/chat/${state.sessionId}/approve`
      ) {
        observations.approvalCalls += 1;
        observations.approvalRequest = JSON.parse((await readBody(request)).toString('utf8'));
        state.approvalSubmitted = true;
        json(response, 200, { status: 'resumed' });
        return;
      }

      if (
        request.method === 'POST' &&
        url.pathname === `/v1/chat/${state.sessionId}/continue`
      ) {
        observations.continuationCalls += 1;
        observations.continuationRequest = JSON.parse((await readBody(request)).toString('utf8'));
        state.continuationSubmitted = true;
        json(response, 200, { status: 'resumed' });
        return;
      }

      if (request.method === 'POST' && url.pathname === '/v1/downloads') {
        observations.downloadCalls += 1;
        observations.downloadRequest = JSON.parse((await readBody(request)).toString('utf8'));
        json(response, 200, {
          download_url: `${state.baseUrl}storage/download?X-Amz-Signature=download-secret`,
          expires_at: NOW,
          expires_in_seconds: 900,
          curl_example: 'sanitized fixture command',
          filename: 'fixture-output.docx',
          format: observations.downloadRequest.format,
        });
        return;
      }

      if (request.method === 'GET' && url.pathname === '/storage/download') {
        observations.signedDownloadCalls += 1;
        observations.signedDownloadAuthorization = request.headers.authorization;
        if (state.scenario === 'download-error') {
          response.writeHead(500, { 'Content-Type': 'text/plain' });
          response.end('fixture download failed');
          return;
        }
        if (state.scenario === 'invalid-signed-url') {
          response.writeHead(403, { 'Content-Type': 'text/plain' }); response.end('expired signed request'); return;
        }
        if (state.scenario === 'download-hang') {
          response.writeHead(200, { 'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
          response.write('partial-export-'); return;
        }
        const format = observations.downloadRequest?.format ?? 'docx';
        const bytes = downloadBytes ?? await createFixtureExport(format);
        const contentType = format === 'pdf'
          ? 'application/pdf'
          : format === 'html'
            ? 'text/html'
            : format === 'markdown'
              ? 'text/markdown'
              : format === 'txt'
                ? 'text/plain'
                : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
        if (state.scenario === 'truncated-download') {
          response.writeHead(200, {
            'Content-Type': contentType,
            'Content-Length': String(bytes.length + 100),
          });
          response.write(bytes.subarray(0, Math.max(1, Math.floor(bytes.length / 2))));
          setImmediate(() => response.destroy()); return;
        }
        const warning = Buffer.from(
          JSON.stringify([{ code: 'fixture_warning', message: 'Fixture export warning' }]),
        ).toString('base64');
        response.writeHead(200, {
          'Content-Type': contentType,
          'X-Export-Warnings': warning,
        });
        for (let offset = 0; offset < bytes.length; offset += 16 * 1024) response.write(bytes.subarray(offset, offset + 16 * 1024));
        response.end();
        return;
      }

      json(response, 404, { detail: `Unhandled fixture route ${request.method} ${url.pathname}` });
    } catch (error) {
      json(response, 500, { detail: error instanceof Error ? error.message : String(error) });
    }
  });

  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  if (address === null || typeof address === 'string') {
    throw new Error('Fixture server did not bind a TCP port.');
  }
  state.baseUrl = `http://127.0.0.1:${address.port}/`;

  return {
    baseUrl: state.baseUrl,
    observations,
    setScenario: (scenario) => { state.scenario = scenario; state.pollCount = 0; },
    close: async () => {
      server.close();
      await once(server, 'close');
    },
  };
}
