import { randomUUID } from 'node:crypto';
import { mkdtemp, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { SuperDocsClient } from '../../dist/api/client.js';
import { pollUntilAction } from '../../dist/core/job-state.js';
import {
  assertRecordingAuthorized, createRecordingFetch, SanitizedCassetteRecorder,
} from './cassette.mjs';

assertRecordingAuthorized(process.env);

const apiBaseUrl = new URL(process.env.SDX_RECORD_API_BASE_URL ?? 'https://api.superdocs.app');
const output = resolve(process.env.SDX_RECORD_OUTPUT ?? 'test/fixtures/cassettes/live-stage4.json');
const directory = await mkdtemp(join(tmpdir(), 'sdx-live-recording-'));
const source = join(directory, 'sdx-disposable-recording.md');
const exported = join(directory, 'sdx-disposable-recording.docx');
const recorder = new SanitizedCassetteRecorder();
const recordingFetch = createRecordingFetch({ apiBaseUrl, recorder });
const client = new SuperDocsClient(process.env.SUPERDOCS_API_KEY, apiBaseUrl, recordingFetch, {
  retryBudgetMs: 110_000,
});
const sessionId = `sdx-recording-${randomUUID()}`;
const filename = 'sdx-disposable-recording.md';

try {
  await writeFile(source, '# Disposable Stage 4 recording\n\nThis synthetic sentence is intentionally repetitive and verbose.\n', { mode: 0o600 });
  const size = (await stat(source)).size;
  const upload = await client.requestUploadUrl(filename, 'text/markdown', size);
  await client.streamUpload(upload.upload_url, source, 'text/markdown', size);
  const processed = await client.processUploadedDocument(upload.upload_id, sessionId, filename);
  const started = await client.startAsyncEdit(sessionId, 'Make the one synthetic sentence concise without changing meaning.', undefined, {
    ...(processed.document_id ? { documentId: processed.document_id } : {}),
  });
  let finished = false;
  while (!finished) {
    const action = await pollUntilAction(client, started.job_id, {
      intervalMs: 2_000, timeoutMs: 110_000, signal: undefined, onProgress: undefined,
    });
    if (action.kind === 'approval') {
      await client.submitApprovalDecisions(sessionId, started.job_id, action.changes.map((change) => ({ change_id: change.id, approved: true })));
    } else if (action.kind === 'continuation') {
      await client.continueLargeEdit(sessionId, started.job_id, true);
    } else {
      finished = true;
    }
  }
  const download = await client.requestDownloadUrl(sessionId, 'docx', 'sdx-disposable-recording');
  await client.streamDownloadAtomically(download.download_url, exported);
  await recorder.write(output);
  process.stderr.write(`Sanitized live cassette written to ${output}; potentially billable edits=1.\n`);
} finally {
  await rm(directory, { recursive: true, force: true });
}
