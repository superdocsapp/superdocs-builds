/**
 * The CLI is the pipeline check, so its contract is its exit code. These tests
 * drive `run()` with an in-memory filesystem rather than spawning processes:
 * same code path, no temporary directories to clean up.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { run } from '../src/cli.js';

function harness(files = {}) {
  const written = new Map();
  const out = [];
  const err = [];
  return {
    written,
    out,
    err,
    stdout: () => out.join('\n'),
    stderr: () => err.join('\n'),
    io: {
      out: (text) => out.push(text),
      err: (text) => err.push(text),
      read: (path) => {
        if (path in files) return files[path];
        if (written.has(path)) return written.get(path);
        if (path.startsWith('fixtures/')) return readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
        throw new Error('ENOENT');
      },
      readStdin: () => files['-'] ?? '',
      write: (path, text) => written.set(path, text),
    },
  };
}

const CLEAN = ['fixtures/01-clean-round-trip/before.html', 'fixtures/01-clean-round-trip/after.html'];
const STRIPPED = ['fixtures/02-attribute-allowlist/before.html', 'fixtures/02-attribute-allowlist/after.html'];
const REORDERED = ['fixtures/07-legal-reorder/before.html', 'fixtures/07-legal-reorder/after.html'];

test('a clean round trip exits 0', () => {
  const h = harness();
  assert.equal(run(['check', ...CLEAN], h.io), 0);
  assert.match(h.stdout(), /clean: every identifier survived/);
});

test('a lost identifier exits 1', () => {
  const h = harness();
  assert.equal(run(['check', ...STRIPPED], h.io), 1);
  assert.match(h.stdout(), /LOST_ATTRIBUTE_STRIPPED/);
});

test('a reorder exits 0, because a reorder is not a loss', () => {
  const h = harness();
  assert.equal(run(['check', ...REORDERED], h.io), 0);
  assert.match(h.stdout(), /BLOCK_MOVED/);
});

test('--fail-on info makes notes fail the build for teams that want that', () => {
  const h = harness();
  assert.equal(run(['check', ...REORDERED, '--fail-on', 'info'], h.io), 1);
});

test('--fail-on never never fails, and still prints the report', () => {
  const h = harness();
  assert.equal(run(['check', ...STRIPPED, '--fail-on', 'never'], h.io), 0);
  assert.match(h.stdout(), /LOST_ATTRIBUTE_STRIPPED/);
});

test('--quiet says nothing when the check passes', () => {
  const h = harness();
  assert.equal(run(['check', ...CLEAN, '--quiet'], h.io), 0);
  assert.equal(h.stdout(), '');
});

test('--quiet still speaks up when the check fails', () => {
  const h = harness();
  assert.equal(run(['check', ...STRIPPED, '--quiet'], h.io), 1);
  assert.match(h.stdout(), /LOST_ATTRIBUTE_STRIPPED/);
});

test('--format json emits a parseable report', () => {
  const h = harness();
  run(['check', ...STRIPPED, '--format', 'json'], h.io);
  const report = JSON.parse(h.stdout());
  assert.equal(report.schemaVersion, 1);
  assert.equal(report.findings[0].rule, 'LOST_ATTRIBUTE_STRIPPED');
});

test('--out writes the report to a file and keeps stdout empty', () => {
  const h = harness();
  run(['check', ...STRIPPED, '--out', 'report.txt'], h.io);
  assert.equal(h.stdout(), '');
  assert.match(h.written.get('report.txt'), /LOST_ATTRIBUTE_STRIPPED/);
});

test('a baseline accepts known findings, and the check goes green', () => {
  const h = harness();
  assert.equal(run(['check', ...STRIPPED, '--baseline', 'base.json', '--update-baseline'], h.io), 0);
  const baseline = JSON.parse(h.written.get('base.json'));
  assert.equal(baseline.accepted.length, 1);
  assert.equal(run(['check', ...STRIPPED, '--baseline', 'base.json'], h.io), 0);
});

test('a baseline does not hide a new finding', () => {
  const h = harness({
    'base.json': JSON.stringify({ baselineVersion: 1, accepted: [{ key: 'LOST_ATTRIBUTE_STRIPPED:deadbeef' }] }),
  });
  assert.equal(run(['check', ...STRIPPED, '--baseline', 'base.json'], h.io), 1);
});

test('one side can come from stdin', () => {
  const h = harness({ '-': '<p data-chunk-id="a">One</p><p data-chunk-id="b">Two</p>' });
  const files = { 'after.html': '<p data-chunk-id="a">One</p><p data-chunk-id="b">Two</p>' };
  const withAfter = harness({ ...files, '-': h.io.readStdin() });
  assert.equal(run(['check', '-', 'after.html'], withAfter.io), 0);
});

test('capture pulls the before side out of a stream', () => {
  const stream = [
    'event: document_sync',
    'data: {"type":"document_sync","content":"<p data-chunk-id=\\"a\\">One</p>"}',
    '',
  ].join('\n');
  const h = harness({ 'stream.log': stream });
  assert.equal(run(['capture', 'stream.log', '--out', 'before.html'], h.io), 0);
  assert.equal(h.written.get('before.html'), '<p data-chunk-id="a">One</p>');
});

test('capture of an unusable payload exits 2, not 1', () => {
  const h = harness({ 'junk.log': 'no events here' });
  assert.equal(run(['capture', 'junk.log'], h.io), 2);
});

test('a missing file exits 2, so a broken check is never read as a pass', () => {
  const h = harness();
  assert.equal(run(['check', 'nope.html', 'also-nope.html'], h.io), 2);
  assert.match(h.stderr(), /could not read nope\.html/);
});

test('bad arguments exit 2 with the usage text', () => {
  for (const args of [
    ['check', 'only-one.html'],
    ['check', ...CLEAN, '--format', 'yaml'],
    ['check', ...CLEAN, '--fail-on', 'catastrophe'],
    ['check', ...CLEAN, '--nonsense'],
    ['wat'],
  ]) {
    const h = harness();
    assert.equal(run(args, h.io), 2, `expected exit 2 for ${args.join(' ')}`);
  }
});

test('no arguments prints usage and exits 2', () => {
  const h = harness();
  assert.equal(run([], h.io), 2);
  assert.match(h.stdout(), /USAGE/);
});

test('--help and --version are exit 0', () => {
  const help = harness();
  assert.equal(run(['--help'], help.io), 0);
  const version = harness();
  assert.equal(run(['--version'], version.io), 0);
  assert.match(version.stdout(), /^\d+\.\d+\.\d+$/);
});

test('rules prints the whole rule table', () => {
  const h = harness();
  assert.equal(run(['rules'], h.io), 0);
  for (const code of ['LOST_ATTRIBUTE_STRIPPED', 'IDS_REGENERATED', 'PART_OMITTED', 'DUPLICATE_ID']) {
    assert.match(h.stdout(), new RegExp(code));
  }
});

test('--id-attribute checks a different identifier', () => {
  const h = harness({
    'b.html': '<p data-block-id="a">One</p><p data-block-id="b">Two</p>',
    'a.html': '<p data-block-id="a">One</p><p>Two</p>',
  });
  assert.equal(run(['check', 'b.html', 'a.html', '--id-attribute', 'data-block-id'], h.io), 1);
});
