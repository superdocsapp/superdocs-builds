import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const apiKey = process.env.SUPERDOCS_API_KEY;
const cliPath = new URL('../../dist/cli.js', import.meta.url).pathname;

function run(args, env) {
  return new Promise((resolve, reject) => {
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
      reject(new Error('Live smoke exceeded its strict two-minute timeout.'));
    }, 120_000);
    child.on('close', (status) => {
      clearTimeout(timer);
      resolve({ status, stdout, stderr });
    });
  });
}

test(
  'optional live review-mode smoke uses at most one billable edit operation',
  { skip: apiKey ? false : 'SUPERDOCS_API_KEY is not set; live smoke pending human execution.' },
  async () => {
    console.error('Live smoke operation cap: 1 potentially billable edit; no approval/export.');
    const health = await fetch('https://api.superdocs.app/health');
    assert.equal(health.ok, true, 'Non-billable health check failed.');

    const directory = await mkdtemp(join(tmpdir(), 'sdx-live-smoke-'));
    const source = join(directory, 'synthetic.md');
    await writeFile(
      source,
      '# Synthetic review\n\nThis synthetic sentence is intentionally verbose and repetitive.\n',
    );
    const startedAt = Date.now();
    try {
      const result = await run(
        [
          'edit',
          source,
          'Make the single sentence concise without changing its meaning.',
          '--json',
          '--poll-interval',
          '2000',
          '--timeout',
          '110000',
        ],
        { ...process.env, HOME: directory, SUPERDOCS_API_KEY: apiKey },
      );
      assert.ok(
        result.status === 3 || result.status === 2,
        `Unexpected sanitized live status ${result.status}: ${result.stderr}`,
      );
      const output = JSON.parse(result.stdout);
      assert.ok(output.status === 'awaiting_approval' || output.status === 'unchanged');
      console.error(
        `Live smoke sanitized status=${output.status} operations<=1 timingMs=${Date.now() - startedAt} outputPath=none`,
      );
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  },
);
