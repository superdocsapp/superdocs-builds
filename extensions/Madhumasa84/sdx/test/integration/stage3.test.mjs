import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { startFixtureServer } from '../fixtures/server.mjs';

const cliPath = new URL('../../dist/cli.js', import.meta.url).pathname;

function runCli(args, options = {}) {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, HOME: options.home, SDX_API_BASE_URL: options.baseUrl, SUPERDOCS_API_KEY: options.key ?? 'fixture-api-key', ...options.env };
    if (options.omitKey) delete env.SUPERDOCS_API_KEY;
    const child = spawn(process.execPath, [cliPath, ...args], { env, cwd: options.cwd });
    let stdout = ''; let stderr = ''; let triggered = false;
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => (stdout += chunk));
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
      // Condition-based SIGINT: fire only after the trigger line appears in stderr,
      // guaranteeing the async-edit HTTP call has returned and activeJobId is set.
      if (!triggered && options.stderrTrigger && stderr.includes(options.stderrTrigger)) {
        triggered = true;
        child.kill('SIGINT');
      }
    });
    child.on('error', reject);
    const timer = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('Stage 3 CLI run timed out.')); }, options.timeout ?? 10_000);
    child.on('close', (status, signal) => { clearTimeout(timer); resolve({ status, signal, stdout, stderr }); });
    if (options.keepInputOpen) {
      child.stdin.write(options.input ?? 'streaming content');
      if (!options.stderrTrigger) {
        // Fall back to timer-based interrupt only when no condition trigger is supplied.
        setTimeout(() => { if (!triggered) { triggered = true; child.kill('SIGINT'); } }, options.interruptAfter ?? 150);
      }
    } else child.stdin.end(options.input ?? '');
  });
}

async function workspace() {
  const directory = await mkdtemp(join('/tmp', 'sdx-stage3-'));
  const home = join(directory, 'home');
  await mkdir(home, { recursive: true });
  const source = join(directory, 'report.md');
  await writeFile(source, '# Q3 report\n\nLong summary.\n');
  return { directory, home, source, output: join(directory, 'report.sdx.docx'), cleanup: () => rm(directory, { recursive: true, force: true }) };
}

function editArgs(source, instruction, extra = []) {
  return ['edit', source, instruction, '--poll-interval', '1', '--timeout', '2', ...extra];
}

test('human edit displays safe section-level diffs, exact job command, and explicit truncation', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source, 'unsafe diff', ['--diff-limit', '50']), { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(result.status, 3, result.stderr);
    assert.match(result.stdout, /Change 1 of 2/); assert.match(result.stdout, /Section: Risks/);
    assert.match(result.stdout, /Old text:/); assert.match(result.stdout, /• First/);
    assert.match(result.stdout, /truncated: \d+ hidden characters across \d+ hidden lines/);
    assert.match(result.stdout, /sdx approve job-1 --accept/);
    assert.doesNotMatch(result.stdout, /\u001b\[/); assert.doesNotMatch(result.stdout, /owned/);
  } finally { await fixture.close(); await files.cleanup(); }
});

test('interactive mixed approval remains item-by-item and supports completion', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source, 'edit', ['--approve']), { baseUrl: fixture.baseUrl, home: files.home, input: 'y\nn\n' });
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(fixture.observations.approvalRequest.changes.map((item) => item.approved), [true, false]);
  } finally { await fixture.close(); await files.cleanup(); }
});

test('JSON edit is one pending object and never prompts', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const result = await runCli(editArgs(files.source, 'edit', ['--json']), { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(result.status, 3, result.stderr); assert.equal(result.stdout.trim().split('\n').length, 1);
    assert.equal(JSON.parse(result.stdout).changes.length, 2); assert.doesNotMatch(result.stderr, /Apply this change/);
  } finally { await fixture.close(); await files.cleanup(); }
});

test('programmatic mixed approval validates live state, completes, and exports stored request', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    assert.equal((await runCli(editArgs(files.source, 'edit', ['--json']), { baseUrl: fixture.baseUrl, home: files.home })).status, 3);
    const result = await runCli(['approve', 'job-1', '--accept', 'change-1', '--reject', 'change-2', '--json', '--poll-interval', '1', '--timeout', '2'], { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(result.status, 0, result.stderr); assert.equal(JSON.parse(result.stdout).status, 'completed');
    assert.equal(await readFile(files.output, 'utf8'), 'fixture-export-bytes');
    assert.deepEqual(fixture.observations.approvalRequest.changes.map((item) => item.approved), [true, false]);
  } finally { await fixture.close(); await files.cleanup(); }
});

for (const [name, args, pattern] of [
  ['missing', ['--accept', 'change-1'], /Missing/],
  ['duplicated', ['--accept', 'change-1,change-1', '--reject', 'change-2'], /Duplicate/],
  ['conflicting', ['--accept', 'change-1', '--reject', 'change-1,change-2'], /Duplicate|both/],
  ['unknown', ['--accept', 'change-1,unknown', '--reject', 'change-2'], /Unknown/],
]) {
  test(`programmatic approval rejects ${name} decisions before submission`, async () => {
    const fixture = await startFixtureServer(); const files = await workspace();
    try {
      await runCli(editArgs(files.source, 'edit', ['--json']), { baseUrl: fixture.baseUrl, home: files.home });
      const result = await runCli(['approve', 'job-1', ...args], { baseUrl: fixture.baseUrl, home: files.home });
      assert.equal(result.status, 10); assert.match(result.stderr, pattern); assert.equal(fixture.observations.approvalCalls, 0);
    } finally { await fixture.close(); await files.cleanup(); }
  });
}

for (const state of ['completed', 'failed', 'cancelled', 'continuation']) {
  test(`approve refuses ${state} job state`, async () => {
    const fixture = await startFixtureServer({ mode: `approve-${state}` }); const files = await workspace();
    try {
      const result = await runCli(['approve', 'job-1', '--accept-all'], { baseUrl: fixture.baseUrl, home: files.home });
      assert.equal(result.status, 10); assert.equal(fixture.observations.approvalCalls, 0);
    } finally { await fixture.close(); await files.cleanup(); }
  });
}

test('named session is created and reused without another upload', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const first = await runCli(editArgs(files.source, 'first edit', ['--session', 'q3-review', '--approve']), { baseUrl: fixture.baseUrl, home: files.home, input: 'y\nn\n' });
    assert.equal(first.status, 0, first.stderr);
    const second = await runCli(editArgs(files.source, 'now shorten conclusion', ['--session', 'q3-review', '--json']), { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(second.status, 3, second.stderr); assert.equal(fixture.observations.uploadCalls, 1); assert.equal(fixture.observations.editCalls, 2);
  } finally { await fixture.close(); await files.cleanup(); }
});

test('named session rejects a different source and changed source without network replacement', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    await runCli(editArgs(files.source, 'edit', ['--session', 'safe', '--json']), { baseUrl: fixture.baseUrl, home: files.home });
    const other = join(files.directory, 'other.md'); await writeFile(other, '# Other\n');
    const different = await runCli(editArgs(other, 'edit', ['--session', 'safe']), { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(different.status, 10); assert.match(different.stderr, /belongs to/);
    await writeFile(files.source, '# Changed locally\n');
    const changed = await runCli(editArgs(files.source, 'edit', ['--session', 'safe']), { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(changed.status, 10); assert.match(changed.stderr, /Local source changed/); assert.equal(fixture.observations.uploadCalls, 1);
  } finally { await fixture.close(); await files.cleanup(); }
});

test('corrupt session state is actionable and removing alias never calls remote delete/archive', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    await runCli(editArgs(files.source, 'edit', ['--session', 'safe', '--json']), { baseUrl: fixture.baseUrl, home: files.home });
    const before = fixture.observations.apiRequests.length;
    const removed = await runCli(['sessions', 'remove', 'safe'], { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(removed.status, 0); assert.match(removed.stdout, /not deleted or archived/); assert.equal(fixture.observations.apiRequests.length, before);
    await writeFile(join(files.home, '.sdx', 'sessions.json'), '{bad');
    const corrupt = await runCli(['sessions', 'list'], { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(corrupt.status, 10); assert.match(corrupt.stderr, /corrupt/);
  } finally { await fixture.close(); await files.cleanup(); }
});

test('stdin and file new flows preserve title, format, safe naming, and cleanup', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const pdf = join(files.directory, 'q3-review.pdf');
    const stdinResult = await runCli(['new', '--title', 'Q3 Review', '--export', 'pdf', '--json'], { baseUrl: fixture.baseUrl, home: files.home, input: '# Notes\n\nSynthetic.\n', cwd: files.directory, env: { TMPDIR: files.directory } });
    assert.equal(stdinResult.status, 0, stdinResult.stderr); assert.equal(JSON.parse(stdinResult.stdout).document.name, 'Q3 Review');
    assert.equal(await readFile(pdf, 'utf8'), 'fixture-export-bytes');
    assert.equal(fixture.observations.uploadRequest.filename, 'Q3 Review.md'); assert.equal(fixture.observations.downloadRequest.format, 'pdf');
    assert.equal((await readdir(files.directory)).some((name) => name.startsWith('sdx-new-')), false);
    const html = join(files.directory, 'notes.html'); await writeFile(html, '<h1>Notes</h1>');
    const docx = join(files.directory, 'notes.docx');
    const fileResult = await runCli(['new', html, '--title', '../Safe Title', '--output', docx], { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(fileResult.status, 0, fileResult.stderr); assert.equal(await readFile(docx, 'utf8'), 'fixture-export-bytes');
  } finally { await fixture.close(); await files.cleanup(); }
});

test('new rejects empty stdin and protects existing output unless overwrite is explicit', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const empty = await runCli(['new', '--title', 'Empty'], { baseUrl: fixture.baseUrl, home: files.home, input: '', cwd: files.directory, env: { TMPDIR: files.directory } });
    assert.equal(empty.status, 10); assert.match(empty.stderr, /empty/); assert.equal((await readdir(files.directory)).some((name) => name.startsWith('sdx-new-')), false);
    const output = join(files.directory, 'protected.docx'); await writeFile(output, 'keep');
    const blocked = await runCli(['new', files.source, '--title', 'Protected', '--output', output], { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(blocked.status, 24); assert.equal(await readFile(output, 'utf8'), 'keep');
    const replaced = await runCli(['new', files.source, '--title', 'Protected', '--output', output, '--overwrite'], { baseUrl: fixture.baseUrl, home: files.home });
    assert.equal(replaced.status, 0, replaced.stderr); assert.equal(await readFile(output, 'utf8'), 'fixture-export-bytes');
  } finally { await fixture.close(); await files.cleanup(); }
});

test('profiles commands parse strict dotfile and select a profile', async () => {
  const files = await workspace();
  try {
    await writeFile(join(files.home, '.sdxrc'), JSON.stringify({ version: 1, activeProfile: 'default', profiles: { work: { exportFormat: 'pdf', timeoutSeconds: 10 } } }));
    const listed = await runCli(['profiles', 'list', '--json'], { home: files.home }); assert.equal(listed.status, 0); assert.deepEqual(JSON.parse(listed.stdout).data.profiles, ['default', 'work']);
    assert.equal((await runCli(['profiles', 'use', 'work'], { home: files.home })).status, 0);
    const shown = await runCli(['profiles', 'show', 'work', '--json'], { home: files.home }); assert.equal(JSON.parse(shown.stdout).data.active, true);
    assert.equal((await runCli(['profiles', 'show', 'missing'], { home: files.home })).status, 10);
  } finally { await files.cleanup(); }
});

test('auth login never echoes the secret and status redacts it', async () => {
  const files = await workspace(); const secret = 'sk_stage3_fixture_secret';
  try {
    const login = await runCli(['auth', 'login'], { home: files.home, input: `${secret}\n`, omitKey: true });
    assert.equal(login.status, 0, login.stderr); assert.doesNotMatch(login.stdout + login.stderr, new RegExp(secret));
    const credentialFile = join(files.home, '.sdx', 'credentials.json'); assert.equal((await stat(credentialFile)).mode & 0o777, 0o600);
    const statusResult = await runCli(['auth', 'status', '--json'], { home: files.home, omitKey: true });
    assert.equal(statusResult.status, 0); assert.equal(JSON.parse(statusResult.stdout).data.source, 'stored');
    assert.doesNotMatch(statusResult.stdout, new RegExp(secret));
    const environment = await runCli(['auth', 'status', '--json'], { home: files.home, key: 'sk_environment_override' });
    assert.equal(JSON.parse(environment.stdout).data.source, 'environment');
  } finally { await files.cleanup(); }
});

for (const shell of ['bash', 'zsh', 'fish']) {
  test(`${shell} completion output is deterministic and complete`, async () => {
    const result = await runCli(['completions', shell], {});
    assert.equal(result.status, 0, result.stderr); assert.ok(result.stdout.length > 100);
    assert.match(result.stdout, /edit/); assert.match(result.stdout, /approve/); assert.match(result.stdout, /--?profile|\bl profile\b/);
  });
}

test('doctor emits actionable human and schema-valid JSON diagnostics without API calls', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const human = await runCli(['doctor'], { baseUrl: fixture.baseUrl, home: files.home }); assert.equal(human.status, 0); assert.match(human.stdout, /PASS node/);
    const json = await runCli(['doctor', '--json'], { baseUrl: fixture.baseUrl, home: files.home }); assert.equal(json.status, 0); assert.ok(JSON.parse(json.stdout).diagnostics.length >= 10);
    assert.ok(JSON.parse(json.stdout).diagnostics.some((item) => item.name === 'operation-ledger-permissions'));
    assert.equal(fixture.observations.apiRequests.length, 0);
  } finally { await fixture.close(); await files.cleanup(); }
});

test('JSON output survives jq parsing when jq is installed', async (t) => {
  if (spawnSync('jq', ['--version'], { encoding: 'utf8' }).status !== 0) return t.skip('jq unavailable');
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const edit = await runCli(editArgs(files.source, 'edit', ['--json']), { baseUrl: fixture.baseUrl, home: files.home });
    const jq = spawnSync('jq', ['.changes'], { input: edit.stdout, encoding: 'utf8' }); assert.equal(jq.status, 0, jq.stderr); assert.match(jq.stdout, /change-1/);
  } finally { await fixture.close(); await files.cleanup(); }
});

test('Ctrl+C returns 130 and removes streamed-new temporary input', async () => {
  const fixture = await startFixtureServer(); const files = await workspace();
  try {
    const result = await runCli(['new', '--title', 'Interrupted'], { baseUrl: fixture.baseUrl, home: files.home, cwd: files.directory, env: { TMPDIR: files.directory }, keepInputOpen: true });
    assert.equal(result.status, 130, result.stderr); assert.equal((await readdir(files.directory)).some((name) => name.startsWith('sdx-new-')), false);
  } finally { await fixture.close(); await files.cleanup(); }
});

test('Ctrl+C reports a possibly-running remote edit job without claiming cancellation', async () => {
  const fixture = await startFixtureServer({ mode: 'stuck' }); const files = await workspace();
  try {
    // Use condition-based synchronisation: send SIGINT only after the first poll
    // result appears in stderr, guaranteeing onJobStarted has set activeJobId.
    // The 'stuck' fixture always responds 'pending', so 'Job pending' is the
    // earliest safe marker that proves startAsyncEdit succeeded.
    const result = await runCli(
      editArgs(files.source, 'keep waiting', ['--timeout', '30']),
      { baseUrl: fixture.baseUrl, home: files.home, keepInputOpen: true, input: '',
        stderrTrigger: 'Job pending' },
    );
    assert.equal(result.status, 130, result.stderr);
    assert.match(result.stderr, /Remote job job-1 may still be running/);
    assert.match(result.stderr, /not cancelled/);
  } finally { await fixture.close(); await files.cleanup(); }
});
