import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import test from 'node:test';
import { preview, approve, resume, publicationDryRun } from '../src/workflow.js';
import { loadManifest } from '../src/state.js';
import { parseCanonical } from '../src/canonical.js';
import { sha256 } from '../src/hash.js';
import { ChangelogError } from '../src/errors.js';
import { validatePdf, validateDocx } from '../src/export.js';

const base = new URL('../fixtures/changelog.md', import.meta.url).pathname;
const releases = (number) => new URL(`../fixtures/releases/release-${String(number).padStart(2, '0')}.json`, import.meta.url).pathname;

async function workspace() {
  const dir = await mkdtemp(join(tmpdir(), 'changelog-integration-')); const canonical = join(dir, 'changelog.md'); const state = join(dir, 'state'); const output = join(dir, 'artifacts');
  await cp(base, canonical); return { dir, canonical, state, output, cleanup: () => rm(dir, { recursive: true, force: true }) };
}

async function approveAll(run, stateDir, outputDir) {
  return approve({ runId: run.run_id, stateDir, outputDir, accept: run.pending_items });
}

test('preview → partial decisions → mixed approval → append → export', async () => {
  const files = await workspace();
  try {
    const before = await readFile(files.canonical); const run = await preview({ canonicalPath: files.canonical, releasePath: releases(1), stateDir: files.state });
    const partial = await approve({ runId: run.run_id, stateDir: files.state, reject: [run.pending_items[1]] });
    await assert.rejects(() => approve({ runId: run.run_id, stateDir: files.state, reject: [run.pending_items[1]] }), /duplicate or conflicting/);
    assert.equal(partial.status, 'awaiting_decisions'); assert.deepEqual(partial.pending_items, [run.pending_items[0]]);
    const done = await approve({ runId: run.run_id, stateDir: files.state, accept: [run.pending_items[0]], outputDir: files.output });
    assert.equal(done.status, 'completed'); const after = await readFile(files.canonical);
    assert.equal(after.subarray(0, before.length).equals(before), true); assert.match(after.toString(), /No-spend previews/); assert.doesNotMatch(after.toString(), /Stable hashes/);
    validatePdf(await readFile(done.outputs.pdf.path)); validateDocx(await readFile(done.outputs.docx.path));
    const manifest = await loadManifest(files.state, run.run_id); assert.equal(manifest.output_hashes.canonical_sha256, sha256(after)); assert.equal(manifest.feedback?.[run.pending_items[1]], undefined);
  } finally { await files.cleanup(); }
});

test('ten sequential releases retain every historical prefix byte-for-byte', async () => {
  const files = await workspace();
  try {
    for (let index = 1; index <= 10; index += 1) {
      const before = await readFile(files.canonical); const run = await preview({ canonicalPath: files.canonical, releasePath: releases(index), stateDir: files.state });
      const done = await approveAll(run, files.state, files.output); assert.equal(done.status, 'completed');
      const after = await readFile(files.canonical); assert.equal(after.subarray(0, before.length).equals(before), true);
    }
    const final = parseCanonical(await readFile(files.canonical)); assert.equal(final.releases.length, 11);
    const eleventh = join(files.dir, 'release-11.json'); const tenth = JSON.parse(await readFile(releases(10), 'utf8')); tenth.release_id = '2026.11'; await writeFile(eleventh, JSON.stringify(tenth));
    await assert.rejects(() => preview({ canonicalPath: files.canonical, releasePath: eleventh, stateDir: files.state }), /stopping rule/);
    await assert.rejects(() => preview({ canonicalPath: files.canonical, releasePath: releases(1), stateDir: files.state }), /duplicate release|stopping rule/);
  } finally { await files.cleanup(); }
});

test('duplicate, stale, incomplete, and self-generated updates are rejected safely', async () => {
  const files = await workspace();
  try {
    const first = await preview({ canonicalPath: files.canonical, releasePath: releases(1), stateDir: files.state });
    await approveAll(first, files.state, files.output);
    await assert.rejects(() => preview({ canonicalPath: files.canonical, releasePath: releases(1), stateDir: files.state }), /duplicate release/);
    const pending = await preview({ canonicalPath: files.canonical, releasePath: releases(2), stateDir: files.state });
    await assert.rejects(() => approve({ runId: pending.run_id, stateDir: files.state, accept: ['unknown'] }), /unknown/);
    const generated = join(files.dir, 'generated.json'); await writeFile(generated, JSON.stringify({ release_id: '2026.99', title: 'Generated', date: '2026-12-01', metadata: { origin: 'superdocs-changelog-maintainer' }, items: [{ id: 'x', category: 'Added', title: 'x', body: 'x' }] }));
    await assert.rejects(() => preview({ canonicalPath: files.canonical, releasePath: generated, stateDir: files.state }), /generated/);
    const changed = join(files.dir, 'changed.md'); await cp(files.canonical, changed); const run = await preview({ canonicalPath: changed, releasePath: releases(2), stateDir: join(files.dir, 'changed-state') }); await writeFile(changed, `${await readFile(changed, 'utf8')}\n# out-of-band\n`); await assert.rejects(() => approve({ runId: run.run_id, stateDir: join(files.dir, 'changed-state'), accept: run.pending_items }), /changed since preview/);
  } finally { await files.cleanup(); }
});

test('interruption after preview, approval, append, and export resumes same run', async () => {
  for (const checkpoint of ['previewed', 'decisions_recorded', 'append_started', 'export']) {
    const files = await workspace();
    try {
      if (checkpoint === 'previewed') await assert.rejects(() => preview({ canonicalPath: files.canonical, releasePath: releases(1), stateDir: files.state, failAt: checkpoint }), /interruption/);
      else {
        const run = await preview({ canonicalPath: files.canonical, releasePath: releases(1), stateDir: files.state });
        await assert.rejects(() => approve({ runId: run.run_id, stateDir: files.state, outputDir: files.output, accept: run.pending_items, failAt: checkpoint }), /interruption/);
        const recovered = await resume({ runId: run.run_id, stateDir: files.state, outputDir: files.output }); assert.equal(recovered.status, 'completed');
        const text = await readFile(files.canonical, 'utf8'); assert.equal((text.match(/changelog:release-id=2026\.01/g) || []).length, 1);
      }
    } finally { await files.cleanup(); }
  }
});



test('tampered approved bytes cannot be recovered after append checkpoint', async () => {
  const files = await workspace();
  try {
    const run = await preview({ canonicalPath: files.canonical, releasePath: releases(1), stateDir: files.state });
    await assert.rejects(() => approve({ runId: run.run_id, stateDir: files.state, outputDir: files.output, accept: run.pending_items, failAt: 'append_started' }), /interruption/);
    const statePath = join(files.state, `${run.run_id}.json`); const manifest = JSON.parse(await readFile(statePath, 'utf8')); manifest.approved_block = `${manifest.approved_block}tampered`;
    await writeFile(statePath, JSON.stringify(manifest));
    await assert.rejects(() => resume({ runId: run.run_id, stateDir: files.state, outputDir: files.output }), /approved block hash/);
    assert.equal((await readFile(files.canonical, 'utf8')).includes('2026.01'), false);
  } finally { await files.cleanup(); }
});

test('completed reruns are idempotent and publication dry-run carries integrity hashes', async () => {
  const files = await workspace();
  try {
    const run = await preview({ canonicalPath: files.canonical, releasePath: releases(1), stateDir: files.state });
    const done = await approveAll(run, files.state, files.output); const before = await readFile(files.canonical);
    const again = await approve({ runId: run.run_id, stateDir: files.state, outputDir: files.output, accept: run.pending_items });
    const recovered = await resume({ runId: run.run_id, stateDir: files.state, outputDir: files.output });
    assert.equal(again.status, 'completed'); assert.equal(recovered.status, 'completed'); assert.deepEqual(await readFile(files.canonical), before);
    const plan = await publicationDryRun({ runId: run.run_id, stateDir: files.state, repository: 'example/changelog', base: 'main' });
    assert.equal(plan.network_calls, 0); assert.equal(plan.integrity.canonical_sha256, done.output_hashes.canonical_sha256); assert.equal(plan.integrity.pdf_sha256, done.output_hashes.pdf_sha256); assert.equal(plan.integrity.docx_sha256, done.output_hashes.docx_sha256);
  } finally { await files.cleanup(); }
});

test('existing output is never overwritten by approval', async () => {
  const files = await workspace();
  try {
    const run = await preview({ canonicalPath: files.canonical, releasePath: releases(1), stateDir: files.state });
    await mkdir(files.output, { recursive: true }); const outputPath = join(files.output, 'changelog-2026.01.pdf'); await writeFile(outputPath, 'sentinel');
    await assert.rejects(() => approveAll(run, files.state, files.output), /output already exists/); assert.equal(await readFile(outputPath, 'utf8'), 'sentinel');
    assert.equal((await readFile(files.canonical, 'utf8')).includes('2026.01'), false);
  } finally { await files.cleanup(); }
});


test('corrupt durable state fails with an actionable state error', async () => {
  const files = await workspace();
  try {
    await mkdir(files.state, { recursive: true });
    await writeFile(join(files.state, 'run_corrupt.json'), JSON.stringify({ version: 1, run_id: 'run_corrupt', status: 'completed', release_id: 'x', input_sha256: 'bad', historical_prefix_sha256: 'bad', candidate_block_sha256: 'bad', expected_canonical_sha256: 'bad', candidate_block: 'x', decisions: {}, checkpoints: [] }));
    await assert.rejects(() => loadManifest(files.state, 'run_corrupt'), (error) => error.code === 'CORRUPT_STATE' && /invalid durable state|missing required|invalid release/.test(error.message));
  } finally { await files.cleanup(); }
});

test('publication adapter is a dry run with zero network and credentials', async () => {
  const files = await workspace();
  try {
    const run = await preview({ canonicalPath: files.canonical, releasePath: releases(1), stateDir: files.state }); const plan = await publicationDryRun({ runId: run.run_id, stateDir: files.state, repository: 'example/changelog', base: 'main' });
    assert.equal(plan.mode, 'dry-run'); assert.equal(plan.would_publish, false); assert.equal(plan.network_calls, 0); assert.equal(plan.credentials_used, false);
  } finally { await files.cleanup(); }
});

test('same changelog serializes concurrent updates while different files proceed', async () => {
  const first = await workspace(); const second = await workspace();
  try {
    const r1 = await preview({ canonicalPath: first.canonical, releasePath: releases(1), stateDir: first.state }); const r2 = await preview({ canonicalPath: first.canonical, releasePath: releases(2), stateDir: first.state });
    const results = await Promise.allSettled([approve({ runId: r1.run_id, stateDir: first.state, outputDir: first.output, accept: r1.pending_items }), approve({ runId: r2.run_id, stateDir: first.state, outputDir: first.output, accept: r2.pending_items })]);
    assert.equal(results.filter((item) => item.status === 'fulfilled').length, 1); assert.equal(results.filter((item) => item.status === 'rejected').length, 1);
    const other = await preview({ canonicalPath: second.canonical, releasePath: releases(1), stateDir: second.state }); const otherDone = await approveAll(other, second.state, second.output); assert.equal(otherDone.status, 'completed');
  } finally { await first.cleanup(); await second.cleanup(); }
});

test('clean installed entry point smoke has no credential path', async () => {
  const cli = new URL('../src/cli.js', import.meta.url).pathname;
  const result = await new Promise((resolve, reject) => { const child = spawn(process.execPath, [cli, '--version'], { env: { ...process.env, SUPERDOCS_API_KEY: undefined } }); let out = ''; child.stdout.on('data', (chunk) => { out += chunk; }); child.on('error', reject); child.on('close', (code) => resolve({ code, out })); });
  assert.equal(result.code, 0); assert.equal(result.out.trim(), '0.1.0');
});
