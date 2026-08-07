import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { startFixtureServer } from '../fixtures/server.mjs';

const cliPath = new URL('../../dist/cli.js', import.meta.url).pathname;

function runCli(args, { baseUrl, key = 'fixture-api-key', input = '', omitKey = false, home }) {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, SDX_API_BASE_URL: baseUrl };
    if (omitKey) {
      delete env.SUPERDOCS_API_KEY;
      // Isolate HOME so that a real ~/.sdx/credentials.json on the developer
      // machine cannot satisfy the missing-credential check.
      env.HOME = home ?? '/tmp/sdx-no-home-isolated';
    } else {
      env.SUPERDOCS_API_KEY = key;
    }
    const child = spawn(process.execPath, [cliPath, ...args], { env });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => (stdout += chunk));
    child.stderr.on('data', (chunk) => (stderr += chunk));
    child.on('error', reject);
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error('Compiled CLI fixture run timed out.'));
    }, 10_000);
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      resolve({ status: code, signal, stdout, stderr });
    });
    child.stdin.end(input);
  });
}

async function workspace() {
  const directory = await mkdtemp(join(tmpdir(), 'sdx-stage2-'));
  const source = join(directory, 'report.md');
  await writeFile(source, '# Q3 report\n\nLong summary.\n');
  return {
    directory,
    source,
    output: join(directory, 'report.sdx.docx'),
    cleanup: () => rm(directory, { recursive: true, force: true }),
  };
}

function editArgs(source, output, instruction, extra = []) {
  return [
    'edit',
    source,
    instruction,
    '--output',
    output,
    '--poll-interval',
    '1',
    '--timeout',
    '2000',
    ...extra,
  ];
}

test('compiled CLI completes the full local fixture vertical slice', async (t) => {
  const fixture = await startFixtureServer();
  const files = await workspace();
  try {
    const result = await runCli(
      editArgs(files.source, files.output, 'tighten the executive summary', [
        '--approve',
      ]),
      { baseUrl: fixture.baseUrl, input: 'y\nn\n' },
    );
    const observed = fixture.observations;

    await t.test('compiled CLI exits successfully only after export', () => {
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, /Exported verified document/);
    });
    await t.test('pre-signed upload request uses the documented body', () => {
      assert.deepEqual(observed.uploadRequest, {
        filename: 'report.md',
        content_type: 'text/markdown',
        size_bytes: Buffer.byteLength('# Q3 report\n\nLong summary.\n'),
        purpose: 'document',
      });
    });
    await t.test('source bytes reach the signed PUT route', () => {
      assert.equal(
        observed.uploadedBytes.toString('utf8'),
        '# Q3 report\n\nLong summary.\n',
      );
    });
    await t.test('SuperDocs credentials are absent from signed upload', () => {
      assert.equal(observed.signedUploadAuthorization, undefined);
    });
    await t.test('uploaded file is parsed as the editable document', () => {
      assert.equal(observed.processRequest.parse_mode, 'document');
      assert.equal(observed.processRequest.return_html, false);
      assert.equal(observed.processRequest.filename, 'report.md');
    });
    await t.test('async edit uses documented HITL review mode', () => {
      assert.equal(observed.editRequest.approval_mode, 'ask_every_time');
      assert.equal(observed.editRequest.response_mode, 'full');
      assert.equal(observed.editRequest.document_html, undefined);
    });
    await t.test('polling observes pending and in-progress states', () => {
      assert.deepEqual(observed.jobStatuses.slice(0, 2), [
        'pending',
        'in_progress',
      ]);
    });
    await t.test('batch approval includes required top-level approved', () => {
      assert.equal(observed.approvalRequest.approved, true);
      assert.equal(observed.approvalRequest.job_id, 'job-1');
    });
    await t.test('mixed item decisions preserve approved and rejected items', () => {
      assert.deepEqual(observed.approvalRequest.changes, [
        { change_id: 'change-1', approved: true },
        { change_id: 'change-2', approved: false },
      ]);
    });
    await t.test('export is requested from the completed session', () => {
      assert.equal(observed.downloadRequest.session_id, observed.editRequest.session_id);
      assert.equal(observed.downloadRequest.format, 'docx');
    });
    await t.test('SuperDocs credentials are absent from signed download', () => {
      assert.equal(observed.signedDownloadAuthorization, undefined);
    });
    await t.test('export is non-empty and atomically finalized', async () => {
      assert.equal((await readFile(files.output, 'utf8')), 'fixture-export-bytes');
      const names = await readdir(files.directory);
      assert.equal(names.some((name) => name.endsWith('.tmp')), false);
    });
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('pending review is emitted as one valid JSON object and exits 3', async () => {
  const fixture = await startFixtureServer();
  const files = await workspace();
  try {
    const result = await runCli(
      editArgs(files.source, files.output, 'tighten the executive summary', [
        '--json',
      ]),
      { baseUrl: fixture.baseUrl },
    );
    assert.equal(result.status, 3, result.stderr);
    assert.equal(result.stdout.trim().split('\n').length, 1);
    const output = JSON.parse(result.stdout);
    assert.equal(output.status, 'awaiting_approval');
    assert.equal(output.changes.length, 2);
    assert.equal(output.changes[1].operation, 'create');
    assert.equal(output.changes[1].chunkId, 'chunk-2');
    assert.equal(fixture.observations.approvalCalls, 0);
    assert.equal(fixture.observations.downloadCalls, 0);
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('all explicitly rejected changes are submitted and map to exit 4', async () => {
  const fixture = await startFixtureServer();
  const files = await workspace();
  try {
    const result = await runCli(
      editArgs(files.source, files.output, 'tighten the executive summary', [
        '--approve',
      ]),
      { baseUrl: fixture.baseUrl, input: 'n\nn\n' },
    );
    assert.equal(result.status, 4, result.stderr);
    assert.deepEqual(
      fixture.observations.approvalRequest.changes.map((item) => item.approved),
      [false, false],
    );
    assert.equal(fixture.observations.downloadCalls, 0);
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('already-satisfied edit maps to exit 2 without export', async () => {
  const fixture = await startFixtureServer();
  const files = await workspace();
  try {
    const result = await runCli(
      editArgs(files.source, files.output, 'already satisfied'),
      { baseUrl: fixture.baseUrl },
    );
    assert.equal(result.status, 2, result.stderr);
    assert.match(result.stdout, /No document changes/);
    assert.equal(fixture.observations.downloadCalls, 0);
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('continuation prompt calls continue and never approval', async () => {
  const fixture = await startFixtureServer();
  const files = await workspace();
  try {
    const result = await runCli(
      editArgs(files.source, files.output, 'continue the large edit', ['--approve']),
      { baseUrl: fixture.baseUrl, input: 'y\n' },
    );
    assert.equal(result.status, 0, result.stderr);
    assert.equal(fixture.observations.continuationCalls, 1);
    assert.deepEqual(fixture.observations.continuationRequest, {
      job_id: 'job-1',
      continue: true,
    });
    assert.equal(fixture.observations.approvalCalls, 0);
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('malformed encoded change fails honestly with exit 25', async () => {
  const fixture = await startFixtureServer();
  const files = await workspace();
  try {
    const result = await runCli(
      editArgs(files.source, files.output, 'malformed pending changes', ['--json']),
      { baseUrl: fixture.baseUrl },
    );
    assert.equal(result.status, 25, result.stderr);
    const output = JSON.parse(result.stdout);
    assert.equal(output.status, 'failed');
    assert.equal(output.error.code, 'SDX_25');
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

for (const [instruction, terminalStatus] of [
  ['fail job', 'failed'],
  ['cancel job', 'cancelled'],
]) {
  test(`${terminalStatus} jobs never report success`, async () => {
    const fixture = await startFixtureServer();
    const files = await workspace();
    try {
      const result = await runCli(editArgs(files.source, files.output, instruction), {
        baseUrl: fixture.baseUrl,
      });
      assert.equal(result.status, 22);
      assert.equal(result.stdout, '');
      assert.match(result.stderr, new RegExp(terminalStatus));
    } finally {
      await fixture.close();
      await files.cleanup();
    }
  });
}

test('poll timeout terminates safely', async () => {
  const fixture = await startFixtureServer({ mode: 'stuck' });
  const files = await workspace();
  try {
    const args = editArgs(files.source, files.output, 'keep waiting');
    const timeoutIndex = args.indexOf('--timeout') + 1;
    args[timeoutIndex] = '0.02';
    const result = await runCli(args, { baseUrl: fixture.baseUrl });
    assert.equal(result.status, 22);
    assert.match(result.stderr, /actionable state/);
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('failed export leaves no final or temporary file', async () => {
  const fixture = await startFixtureServer({ mode: 'download-error' });
  const files = await workspace();
  try {
    const result = await runCli(
      editArgs(files.source, files.output, 'tighten the executive summary', [
        '--approve',
      ]),
      { baseUrl: fixture.baseUrl, input: 'y\nn\n' },
    );
    assert.equal(result.status, 24, result.stderr);
    const names = await readdir(files.directory);
    assert.equal(names.includes('report.sdx.docx'), false);
    assert.equal(names.some((name) => name.endsWith('.tmp')), false);
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('missing environment key exits 20 before any API request', async () => {
  const fixture = await startFixtureServer();
  const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source, files.output, 'edit'), {
      baseUrl: fixture.baseUrl,
      omitKey: true,
    });
    assert.equal(result.status, 20);
    assert.match(result.stderr, /SUPERDOCS_API_KEY/);
    assert.equal(fixture.observations.apiRequests.length, 0);
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('HTTP authentication failure maps to exit 20', async () => {
  const fixture = await startFixtureServer({ expectedKey: 'different-key' });
  const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source, files.output, 'edit'), {
      baseUrl: fixture.baseUrl,
    });
    assert.equal(result.status, 20);
    assert.match(result.stderr, /HTTP 401/);
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('successful response schema mismatch maps to exit 25', async () => {
  const fixture = await startFixtureServer({ mode: 'parse-mismatch' });
  const files = await workspace();
  try {
    const result = await runCli(
      editArgs(files.source, files.output, 'edit', ['--json']),
      { baseUrl: fixture.baseUrl },
    );
    assert.equal(result.status, 25);
    assert.equal(JSON.parse(result.stdout).error.code, 'SDX_25');
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('interactive approval and JSON mode conflict before network access', async () => {
  const fixture = await startFixtureServer();
  const files = await workspace();
  try {
    const result = await runCli(
      editArgs(files.source, files.output, 'edit', ['--approve', '--json']),
      { baseUrl: fixture.baseUrl },
    );
    assert.equal(result.status, 10);
    assert.equal(JSON.parse(result.stdout).status, 'failed');
    assert.equal(fixture.observations.apiRequests.length, 0);
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});

test('signed URL and API key are redacted from transfer errors', async () => {
  const fixture = await startFixtureServer({ mode: 'signed-upload-error' });
  const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source, files.output, 'edit'), {
      baseUrl: fixture.baseUrl,
    });
    assert.equal(result.status, 23);
    assert.doesNotMatch(result.stderr, /fixture-secret/);
    assert.doesNotMatch(result.stderr, /fixture-api-key/);
    assert.match(result.stderr, /REDACTED|%5BREDACTED%5D/);
  } finally {
    await fixture.close();
    await files.cleanup();
  }
});
