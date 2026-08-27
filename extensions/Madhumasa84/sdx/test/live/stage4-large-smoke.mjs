import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import JSZip from 'jszip';

import { SuperDocsClient } from '../../dist/api/client.js';
import { pollUntilAction } from '../../dist/core/job-state.js';
import { generateStyledDocx } from '../stress/generate-docx.mjs';

const apiKey = process.env.SUPERDOCS_API_KEY;

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

async function assertDocx(path, expectedMarker) {
  const bytes = await readFile(path);
  assert.ok(bytes.length > 0, 'export must be non-empty');
  const zip = await JSZip.loadAsync(bytes);
  const document = await zip.file('word/document.xml').async('string');
  assert.match(document, new RegExp(expectedMarker));
  assert.equal((document.match(/w:type="page"/g) ?? []).length, 119);
  assert.ok(zip.file('word/header1.xml'));
  assert.ok(zip.file('word/footer1.xml'));
  return bytes;
}

test(
  'optional live Stage 4 smoke edits and exports the deterministic 120-page DOCX',
  { skip: apiKey ? false : 'SUPERDOCS_API_KEY is not set; live Stage 4 smoke pending human execution.', timeout: 900_000 },
  async () => {
    const directory = await mkdtemp(join(tmpdir(), 'sdx-live-stage4-'));
    const source = join(directory, 'styled-120-pages.docx');
    const output = join(directory, 'edited-120-pages.docx');
    try {
      const sourceBytes = await generateStyledDocx(source);
      const sourceHash = sha256(sourceBytes);
      const client = new SuperDocsClient(apiKey, new URL(process.env.SDX_API_BASE_URL ?? 'https://api.superdocs.app'), fetch, {
        retryBudgetMs: 600_000,
      });
      const sessionId = `sdx-live-stage4-${randomUUID()}`;
      const upload = await client.requestUploadUrl('styled-120-pages.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', sourceBytes.length);
      await client.streamUpload(upload.upload_url, source, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', sourceBytes.length);
      const processed = await client.processUploadedDocument(upload.upload_id, sessionId, 'styled-120-pages.docx');
      const started = await client.startAsyncEdit(
        sessionId,
        'On page 120, replace the exact marker SDX_TARGET_PAGE_120_ORIGINAL with SDX_TARGET_PAGE_120_EDITED. Make no other changes.',
        undefined,
        processed.document_id ? { documentId: processed.document_id } : {},
      );

      let approvalItems = 0;
      let continuations = 0;
      while (true) {
        const action = await pollUntilAction(client, started.job_id, {
          intervalMs: 3_000,
          timeoutMs: 600_000,
          signal: undefined,
          onProgress: undefined,
        });
        if (action.kind === 'completed') break;
        if (action.kind === 'continuation') {
          continuations += 1;
          await client.continueLargeEdit(sessionId, started.job_id, true);
          continue;
        }
        const decisions = action.changes.map((change) => ({ change_id: change.id, approved: true }));
        assert.ok(decisions.length > 0, 'approval round must contain explicit item decisions');
        approvalItems += decisions.length;
        await client.submitApprovalDecisions(sessionId, started.job_id, decisions);
      }

      const download = await client.requestDownloadUrl(sessionId, 'docx', 'edited-120-pages');
      const downloaded = await client.streamDownloadAtomically(download.download_url, output);
      const outputBytes = await assertDocx(output, 'SDX_TARGET_PAGE_120_EDITED');
      assert.equal(sha256(await readFile(source)), sourceHash, 'source must remain untouched');
      assert.equal(downloaded.bytes, outputBytes.length);
      assert.ok(downloaded.bytes > 0);
      const usage = client.usage;
      process.stderr.write(`Live Stage 4 sanitized status=completed approvalItems=${approvalItems} continuations=${continuations} inputBytes=${sourceBytes.length} inputSha256=${sourceHash} outputBytes=${outputBytes.length} outputSha256=${sha256(outputBytes)} apiCalls=${usage.apiCalls} uploadedBytes=${usage.uploadedBytes} downloadedBytes=${usage.downloadedBytes} operations<=1.\n`);
      assert.ok((await stat(output)).size > 0);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  },
);
