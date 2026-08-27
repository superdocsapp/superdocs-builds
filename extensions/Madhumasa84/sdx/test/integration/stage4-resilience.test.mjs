import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';

import { assertValidFixtureExport } from '../fixtures/export-artifacts.mjs';
import { startFixtureServer } from '../fixtures/server.mjs';

const cliPath = new URL('../../dist/cli.js', import.meta.url).pathname;

function runCli(args, { home, baseUrl, input = '' }) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [cliPath, ...args], {
      env: { ...process.env, HOME: home, SDX_API_BASE_URL: baseUrl, SUPERDOCS_API_KEY: 'fixture-api-key' },
    });
    let stdout = ''; let stderr = '';
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', (value) => (stdout += value));
    child.stderr.on('data', (value) => (stderr += value));
    child.on('error', reject); child.stdin.end(input);
    child.on('close', (status) => resolve({ status, stdout, stderr }));
  });
}

async function workspace() {
  const directory = await mkdtemp('/tmp/sdx-stage4-retry-');
  const home = join(directory, 'home'); await mkdir(home, { recursive: true });
  const source = join(directory, 'source.md'); await writeFile(source, '# Retry fixture\n\nSafe content.\n');
  return { directory, home, source };
}

function editArgs(source) {
  return ['edit', source, 'update risks', '--json', '--poll-interval', '1', '--timeout', '2'];
}

test('fixture application 429 retries exactly once after a short Retry-After', async () => {
  const fixture = await startFixtureServer({ mode: 'application-429-short' }); const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source), { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(result.status, 3, result.stderr);
    assert.equal(fixture.observations.uploadCalls, 2);
    assert.match(result.stderr, /application-429/);
    assert.equal(JSON.parse(result.stdout).status, 'awaiting_approval');
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('fixture application 429 beyond budget fails once with structured safe metadata', async () => {
  const fixture = await startFixtureServer({ mode: 'application-429-long' }); const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source), { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(result.status, 21, result.stderr);
    assert.equal(fixture.observations.uploadCalls, 1);
    const output = JSON.parse(result.stdout);
    assert.equal(output.error.details.retryAfterSeconds, 1_209_600);
    assert.equal(output.error.details.attemptCount, 1);
    assert.equal(output.error.details.usageRemaining, '0');
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('fixture infrastructure 429 retries with bounded backoff and exact call count', async () => {
  const fixture = await startFixtureServer({ mode: 'infrastructure-429' }); const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source), { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(result.status, 3, result.stderr);
    assert.equal(fixture.observations.uploadCalls, 3);
    assert.match(result.stderr, /infrastructure-429/);
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('fixture transient 503 retries only job polling GET and preserves one chat submission', async () => {
  const fixture = await startFixtureServer({ mode: 'transient-503' }); const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source), { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(result.status, 3, result.stderr);
    assert.equal(fixture.observations.editCalls, 1);
    assert.equal(fixture.observations.jobCalls, 5);
    assert.match(result.stderr, /transient/);
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('accepted chat with dropped response records unknown state and never submits twice', async () => {
  const fixture = await startFixtureServer({ mode: 'drop-after-chat-accept' }); const files = await workspace();
  try {
    const args = ['edit', files.source, 'private instruction must not persist', '--session', 'ledger-session', '--json', '--timeout', '2'];
    const first = await runCli(args, { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(first.status, 22, first.stderr);
    assert.equal(fixture.observations.editCalls, 1);
    const firstOutput = JSON.parse(first.stdout);
    assert.equal(firstOutput.error.details.remoteState, 'unknown');
    assert.match(firstOutput.error.message, /do not repeat/i);

    const ledgerText = await (await import('node:fs/promises')).readFile(join(files.home, '.sdx', 'operations.json'), 'utf8');
    assert.doesNotMatch(ledgerText, /private instruction must not persist/);
    const records = Object.values(JSON.parse(ledgerText).operations);
    assert.equal(records.length, 1);
    assert.equal(records[0].state, 'unknown');
    assert.equal(records[0].jobId, null);
    assert.match(records[0].fingerprint, /^[a-f0-9]{64}$/);

    const second = await runCli(args, { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(second.status, 22, second.stderr);
    assert.equal(fixture.observations.editCalls, 1);
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('connection drop before request acceptance is conservatively not retried', async () => {
  const fixture = await startFixtureServer({ mode: 'drop-before-chat-accept' }); const files = await workspace();
  try {
    const result = await runCli(['edit', files.source, 'edit', '--json', '--timeout', '2'], { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(result.status, 22, result.stderr);
    assert.equal(fixture.observations.editCalls, 0);
    assert.equal(JSON.parse(result.stdout).error.details.remoteState, 'unknown');
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

function startCli(args, { home, baseUrl }) {
  const child = spawn(process.execPath, [cliPath, ...args], {
    env: { ...process.env, HOME: home, SDX_API_BASE_URL: baseUrl, SUPERDOCS_API_KEY: 'fixture-api-key' },
  });
  let stdout = ''; let stderr = '';
  child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
  child.stdout.on('data', (value) => (stdout += value)); child.stderr.on('data', (value) => (stderr += value));
  return { child, result: new Promise((resolve, reject) => { child.on('error', reject); child.on('close', (status, signal) => resolve({ status, signal, stdout, stderr })); }) };
}

async function waitFor(predicate, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (!(await predicate())) {
    if (Date.now() >= deadline) throw new Error('Timed out waiting for fixture observation.');
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

test('killed polling process resumes the same job, approves, and exports with one chat submission', async () => {
  const fixture = await startFixtureServer({ mode: 'stuck' }); const files = await workspace();
  try {
    const first = startCli(['edit', files.source, 'edit page marker', '--session', 'restart-session', '--json', '--poll-interval', '1', '--timeout', '30'], { home: files.home, baseUrl: fixture.baseUrl });
    await waitFor(() => fixture.observations.editCalls === 1);
    await waitFor(async () => {
      try { await (await import('node:fs/promises')).access(join(files.home, '.sdx', 'pending-jobs.json')); return true; }
      catch { return false; }
    });
    first.child.kill('SIGKILL'); await first.result;

    fixture.setScenario('normal');
    const resumed = await runCli(['resume', 'job-1', '--approve', '--poll-interval', '1', '--timeout', '2'], {
      home: files.home, baseUrl: fixture.baseUrl, input: 'y\ny\n',
    });
    assert.equal(resumed.status, 0, resumed.stderr);
    assert.equal(fixture.observations.editCalls, 1);
    assert.equal(fixture.observations.approvalCalls, 1);
    assert.equal(fixture.observations.downloadCalls, 1);
    assert.equal(JSON.parse((await (await import('node:fs/promises')).readFile(join(files.home, '.sdx', 'operations.json'), 'utf8'))).operations[Object.keys(JSON.parse((await (await import('node:fs/promises')).readFile(join(files.home, '.sdx', 'operations.json'), 'utf8'))).operations)[0]].state, 'download-completed');
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('concurrent same-session edit is blocked before duplicate remote work', async () => {
  const fixture = await startFixtureServer({ mode: 'stuck' }); const files = await workspace();
  try {
    const first = startCli(['edit', files.source, 'first', '--session', 'same-session', '--json', '--poll-interval', '1', '--timeout', '30'], { home: files.home, baseUrl: fixture.baseUrl });
    await waitFor(() => fixture.observations.editCalls === 1);
    const second = await runCli(['edit', files.source, 'second', '--session', 'same-session', '--json', '--timeout', '3'], { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(second.status, 10, second.stderr);
    assert.equal(fixture.observations.editCalls, 1);
    assert.match(JSON.parse(second.stdout).error.message, /lock|another sdx process/i);
    first.child.kill('SIGKILL'); await first.result;
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('different named sessions remain concurrently usable', async () => {
  const fixture = await startFixtureServer({ mode: 'stuck' }); const files = await workspace();
  try {
    const first = startCli(['edit', files.source, 'first', '--session', 'session-a', '--json', '--poll-interval', '1', '--timeout', '30'], { home: files.home, baseUrl: fixture.baseUrl });
    const second = startCli(['edit', files.source, 'second', '--session', 'session-b', '--json', '--poll-interval', '1', '--timeout', '30'], { home: files.home, baseUrl: fixture.baseUrl });
    await waitFor(() => fixture.observations.editCalls === 2);
    first.child.kill('SIGKILL'); second.child.kill('SIGKILL');
    await Promise.all([first.result, second.result]);
    assert.equal(fixture.observations.editCalls, 2);
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('expired persisted job fails actionably without replacement submission', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const pending = await runCli(['edit', files.source, 'edit', '--session', 'expired-session', '--json', '--poll-interval', '1', '--timeout', '2'], { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(pending.status, 3, pending.stderr);
    fixture.setScenario('expired-job');
    const resumed = await runCli(['resume', 'job-1', '--json', '--timeout', '2'], { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(resumed.status, 22, resumed.stderr);
    assert.match(JSON.parse(resumed.stdout).error.message, /no longer retained|not resubmitted/i);
    assert.equal(fixture.observations.editCalls, 1);
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

for (const status of [500, 502]) {
  test(`fixture transient ${status} retries polling GET exactly and never repeats chat`, async () => {
    const fixture = await startFixtureServer({ mode: `transient-${status}` }); const files = await workspace();
    try {
      const result = await runCli(editArgs(files.source), { home: files.home, baseUrl: fixture.baseUrl });
      assert.equal(result.status, 3, result.stderr);
      assert.equal(fixture.observations.jobCalls, 5);
      assert.equal(fixture.observations.editCalls, 1);
    } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
  });
}

for (const [mode, expectedStatus] of [['malformed-job-json', 25], ['partial-job-body', 25], ['html-gateway-504', 22]]) {
  test(`${mode} fails safely without repeating remote work`, async () => {
    const fixture = await startFixtureServer({ mode }); const files = await workspace();
    try {
      const result = await runCli(editArgs(files.source), { home: files.home, baseUrl: fixture.baseUrl });
      assert.equal(result.status, expectedStatus, result.stderr);
      assert.equal(fixture.observations.jobCalls, 1);
      assert.equal(fixture.observations.editCalls, 1);
      assert.equal(fixture.observations.uploadCalls, 1);
    } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
  });
}

test('interrupted signed upload is never retried and never reaches processing or chat', async () => {
  const fixture = await startFixtureServer({ mode: 'signed-upload-drop' }); const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source), { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(result.status, 23, result.stderr);
    assert.equal(fixture.observations.uploadCalls, 1);
    assert.equal(fixture.observations.signedUploadCalls, 1);
    assert.equal(fixture.observations.processRequest, undefined);
    assert.equal(fixture.observations.editCalls, 0);
    const records = Object.values(JSON.parse(await readFile(join(files.home, '.sdx', 'operations.json'), 'utf8')).operations);
    assert.equal(records.length, 1);
    assert.equal(records[0].state, 'upload-prepared');
    assert.equal(records[0].uploadId, 'upload-1');
    assert.equal(records[0].sourcePath, files.source);
    assert.doesNotMatch(JSON.stringify(records[0]), /X-Amz-Signature/);
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('repeated HITL rounds require explicit decisions in every round', async () => {
  const fixture = await startFixtureServer({ mode: 'repeated-hitl' }); const files = await workspace();
  try {
    const output = join(files.directory, 'repeated-hitl.docx');
    const result = await runCli(['edit', files.source, 'multi-round edit', '--approve', '--output', output, '--poll-interval', '1', '--timeout', '2'], {
      home: files.home, baseUrl: fixture.baseUrl, input: 'y\ny\ny\n',
    });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(fixture.observations.editCalls, 1);
    assert.equal(fixture.observations.approvalCalls, 2);
    assert.equal(fixture.observations.continuationCalls, 0);
    assert.equal(fixture.observations.downloadCalls, 1);
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('repeated continuation rounds remain explicit and never call approval', async () => {
  const fixture = await startFixtureServer({ mode: 'repeated-continuation' }); const files = await workspace();
  try {
    const output = join(files.directory, 'repeated-continuation.docx');
    const result = await runCli(['edit', files.source, 'large staged operation', '--approve', '--output', output, '--poll-interval', '1', '--timeout', '2'], {
      home: files.home, baseUrl: fixture.baseUrl, input: 'y\ny\n',
    });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(fixture.observations.editCalls, 1);
    assert.equal(fixture.observations.continuationCalls, 2);
    assert.equal(fixture.observations.approvalCalls, 0);
    assert.equal(fixture.observations.downloadCalls, 1);
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

for (const mode of ['truncated-download', 'invalid-signed-url']) {
  test(`${mode} cannot create a final or temporary output`, async () => {
    const fixture = await startFixtureServer({ mode }); const files = await workspace();
    try {
      const output = join(files.directory, `${mode}.docx`);
      const result = await runCli(['edit', files.source, 'edit', '--approve', '--output', output, '--poll-interval', '1', '--timeout', '2'], {
        home: files.home, baseUrl: fixture.baseUrl, input: 'y\nn\n',
      });
      assert.equal(result.status, 24, result.stderr);
      assert.equal(fixture.observations.editCalls, 1);
      assert.equal(fixture.observations.downloadCalls, 1);
      assert.equal(fixture.observations.signedDownloadCalls, 1);
      const names = await readdir(files.directory);
      assert.equal(names.includes(`${mode}.docx`), false);
      assert.equal(names.some((name) => name.startsWith(`.${mode}.docx.`) && name.endsWith('.tmp')), false);
    } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
  });
}

test('termination after completion but before export resumes export without another chat submission', async () => {
  const fixture = await startFixtureServer({ mode: 'download-hang' }); const files = await workspace();
  try {
    const output = join(files.directory, 'completed-before-export.docx');
    const first = startCli(['edit', files.source, 'edit', '--session', 'completed-session', '--approve', '--output', output, '--poll-interval', '1', '--timeout', '30'], {
      home: files.home, baseUrl: fixture.baseUrl,
    });
    first.child.stdin.end('y\ny\n');
    await waitFor(() => fixture.observations.signedDownloadCalls === 1);
    first.child.kill('SIGKILL'); await first.result;
    await assert.rejects(() => readFile(output));

    fixture.setScenario('normal');
    const resumed = await runCli(['resume', 'job-1', '--overwrite', '--poll-interval', '1', '--timeout', '2'], {
      home: files.home, baseUrl: fixture.baseUrl,
    });
    assert.equal(resumed.status, 0, resumed.stderr);
    assert.equal(fixture.observations.editCalls, 1);
    assert.equal(fixture.observations.downloadCalls, 2);
    assert.equal(fixture.observations.signedDownloadCalls, 2);
    await assertValidFixtureExport(await readFile(output), 'docx');
    const names = await readdir(files.directory);
    assert.equal(names.some((name) => name.startsWith('.completed-before-export.docx.') && name.endsWith('.tmp')), false);
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});

test('resume refuses remotely applied changes without persisted explicit-decision proof', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const pending = await runCli(['edit', files.source, 'edit', '--session', 'deny-default-session', '--json', '--poll-interval', '1', '--timeout', '2'], {
      home: files.home, baseUrl: fixture.baseUrl,
    });
    assert.equal(pending.status, 3, pending.stderr);
    fixture.setScenario('unsafe-completed');
    const resumed = await runCli(['resume', 'job-1', '--json', '--timeout', '2'], { home: files.home, baseUrl: fixture.baseUrl });
    assert.equal(resumed.status, 25, resumed.stderr);
    assert.match(JSON.parse(resumed.stdout).error.message, /unexpected completed review-mode job/i);
    assert.equal(fixture.observations.editCalls, 1);
    assert.equal(fixture.observations.approvalCalls, 0);
    assert.equal(fixture.observations.downloadCalls, 0);
  } finally { await fixture.close(); await rm(files.directory, { recursive: true, force: true }); }
});
