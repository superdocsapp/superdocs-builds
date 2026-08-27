import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const cliUrl = new URL('../../dist/cli.js', import.meta.url);

function run(args) {
  return spawnSync(process.execPath, [cliUrl.pathname, ...args], { encoding: 'utf8' });
}

test('sdx --help succeeds and lists Stage 3 commands', () => {
  const result = run(['--help']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Usage: sdx/);
  for (const command of ['edit', 'new', 'approve', 'auth', 'profiles', 'sessions', 'completions', 'doctor']) assert.match(result.stdout, new RegExp(command));
  assert.equal(result.stderr, '');
});

test('sdx --version succeeds', () => {
  const result = run(['--version']);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), '0.1.0');
  assert.equal(result.stderr, '');
});

test('new without a title fails safely with stable invalid-input code', () => {
  const result = run(['new']);
  assert.equal(result.status, 10);
  assert.equal(result.stdout, '');
  assert.match(result.stderr, /--title.*empty/);
});
