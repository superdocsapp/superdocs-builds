import { test, before, after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { readFile, writeFile, rm } from 'node:fs/promises';
import { readDocx } from '@prism/core';
import { server, resetWorkspace } from '../server.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const v1Path = path.join(__dirname, '..', '..', 'delta', 'fixtures', 'contract-v1.docx');
const v2Path = path.join(__dirname, '..', '..', 'delta', 'fixtures', 'contract-v2.docx');

let baseUrl;

before(async () => {
  await new Promise((resolve) => server.listen(0, resolve));
  baseUrl = `http://localhost:${server.address().port}`;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
});

beforeEach(async () => {
  await resetWorkspace();
});

async function post(pathname, body) {
  const res = await fetch(`${baseUrl}${pathname}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  return { status: res.status, body: await res.json() };
}
async function get(pathname) {
  const res = await fetch(`${baseUrl}${pathname}`);
  return { status: res.status, body: await res.json() };
}

test('GET /api/tasks returns all 30 with honest statuses', async () => {
  const { status, body } = await get('/api/tasks');
  assert.equal(status, 200);
  assert.equal(body.tasks.length, 30);
  assert.equal(body.tasks.filter((t) => t.status === 'implemented').length, 4);
});

test('static file serving: index.html and app.js are reachable', async () => {
  const home = await fetch(`${baseUrl}/`);
  assert.equal(home.status, 200);
  assert.match(home.headers.get('content-type'), /text\/html/);
  const script = await fetch(`${baseUrl}/app.js`);
  assert.equal(script.status, 200);
});

test('static file serving refuses path traversal', async () => {
  const res = await fetch(`${baseUrl}/../../etc/passwd`);
  // Browsers/undici normalize '..' out of the URL before it reaches the
  // server in most cases; assert the guard by hitting the handler's own
  // normalize check with an encoded traversal sequence instead.
  const res2 = await fetch(`${baseUrl}/%2e%2e/%2e%2e/etc/passwd`);
  assert.ok([403, 404].includes(res.status));
  assert.ok([403, 404].includes(res2.status));
});

test('full flow: compare -> decide all approved -> apply -> verify -> download -> vault', async () => {
  const [baseB64, targetB64] = await Promise.all([
    readFile(v1Path).then((b) => b.toString('base64')),
    readFile(v2Path).then((b) => b.toString('base64')),
  ]);

  const compareRes = await post('/api/workspace/compare', { baseBase64: baseB64, targetBase64: targetB64 });
  assert.equal(compareRes.status, 200);
  assert.equal(compareRes.body.report.summary.totalChanges, 5);
  const changeIds = compareRes.body.approvalSet.map((e) => e.changeId);
  assert.equal(changeIds.length, 5);

  for (const changeId of changeIds) {
    const decideRes = await post('/api/workspace/decide', { changeId, decision: 'approved' });
    assert.equal(decideRes.status, 200);
  }

  const applyRes = await post('/api/workspace/apply');
  assert.equal(applyRes.status, 200);
  assert.equal(applyRes.body.contentVerified, true);
  assert.ok(applyRes.body.version, 'a vault version should be committed on successful verification');

  const contentCheck = applyRes.body.verification.find((v) => v.area === 'CONTENT');
  assert.equal(contentCheck.status, 'PASS');
  const tablesCheck = applyRes.body.verification.find((v) => v.area === 'TABLES');
  assert.equal(tablesCheck.status, 'NOT_APPLICABLE', 'fixture has no tables');
  const citationsCheck = applyRes.body.verification.find((v) => v.area === 'CITATIONS');
  assert.equal(citationsCheck.status, 'NOT_APPLICABLE', 'PRISM PROOF is not implemented — must not claim PASS for a check that never ran');

  const downloadRes = await fetch(`${baseUrl}/api/workspace/download`);
  assert.equal(downloadRes.status, 200);
  assert.match(downloadRes.headers.get('content-type'), /wordprocessingml/);
  const downloaded = Buffer.from(await downloadRes.arrayBuffer());
  assert.ok(downloaded.length > 1000, 'downloaded file should be a real, non-trivial docx');

  const vaultRes = await get('/api/vault/graph');
  assert.equal(vaultRes.status, 200);
  assert.equal(vaultRes.body.graph.length, 1);
});

test('apply is refused with structured error while decisions are pending', async () => {
  const [baseB64, targetB64] = await Promise.all([
    readFile(v1Path).then((b) => b.toString('base64')),
    readFile(v2Path).then((b) => b.toString('base64')),
  ]);
  await post('/api/workspace/compare', { baseBase64: baseB64, targetBase64: targetB64 });
  const applyRes = await post('/api/workspace/apply');
  assert.equal(applyRes.status, 409);
  assert.ok(applyRes.body.error.whatHappened, 'error must have a WHAT, not just a generic message');
  assert.match(applyRes.body.error.why, /Not yet decided/);
});

test('deciding on an unknown changeId returns a structured 400, not a crash', async () => {
  const [baseB64, targetB64] = await Promise.all([
    readFile(v1Path).then((b) => b.toString('base64')),
    readFile(v2Path).then((b) => b.toString('base64')),
  ]);
  await post('/api/workspace/compare', { baseBase64: baseB64, targetBase64: targetB64 });
  const res = await post('/api/workspace/decide', { changeId: 'delta-9999', decision: 'approved' });
  assert.equal(res.status, 400);
  assert.match(res.body.error.why, /unknown changeId/);
});

test('full flow with a table-containing document: table survives apply and GRID reports PASS', async () => {
  const { Document, Paragraph, TextRun, Table, TableRow, TableCell, Packer } = await import('docx');
  const buildDoc = (feeText) =>
    new Document({
      sections: [{
        children: [
          new Paragraph({ children: [new TextRun('Intro paragraph.')] }),
          new Table({ rows: [new TableRow({ children: [
            new TableCell({ children: [new Paragraph('Item')] }),
            new TableCell({ children: [new Paragraph('Price')] }),
          ] }), new TableRow({ children: [
            new TableCell({ children: [new Paragraph('Widget')] }),
            new TableCell({ children: [new Paragraph('$10')] }),
          ] })] }),
          new Paragraph({ children: [new TextRun(feeText)] }),
        ],
      }],
    });
  const baseB64 = (await Packer.toBuffer(buildDoc('The fee is $50.'))).toString('base64');
  const targetB64 = (await Packer.toBuffer(buildDoc('The fee is $75.'))).toString('base64');

  const compareRes = await post('/api/workspace/compare', { baseBase64: baseB64, targetBase64: targetB64 });
  assert.equal(compareRes.status, 200);
  assert.equal(compareRes.body.report.summary.totalChanges, 1, 'only the fee paragraph changed — table and intro are identical');

  const changeId = compareRes.body.approvalSet[0].changeId;
  await post('/api/workspace/decide', { changeId, decision: 'approved' });

  const applyRes = await post('/api/workspace/apply');
  assert.equal(applyRes.status, 200);
  assert.equal(applyRes.body.contentVerified, true);

  const tablesCheck = applyRes.body.verification.find((v) => v.area === 'TABLES');
  assert.equal(tablesCheck.status, 'PASS', 'GRID must confirm the untouched table survived write-back');
  assert.match(tablesCheck.detail, /structurally identical/);
});

test('apply is refused with a precise reason when a table-containing document also needs a structural change', async () => {
  const { Document, Paragraph, TextRun, Table, TableRow, TableCell, Packer } = await import('docx');
  const buildDoc = (extraSection) =>
    new Document({
      sections: [{
        children: [
          new Paragraph({ children: [new TextRun('Intro.')] }),
          new Table({ rows: [new TableRow({ children: [new TableCell({ children: [new Paragraph('Cell')] })] })] }),
          ...(extraSection ? [new Paragraph({ children: [new TextRun('New section added.')] })] : []),
        ],
      }],
    });
  const baseB64 = (await Packer.toBuffer(buildDoc(false))).toString('base64');
  const targetB64 = (await Packer.toBuffer(buildDoc(true))).toString('base64');

  const compareRes = await post('/api/workspace/compare', { baseBase64: baseB64, targetBase64: targetB64 });
  assert.equal(compareRes.body.report.summary.totalChanges, 1, 'one structural addition');
  const changeId = compareRes.body.approvalSet[0].changeId;
  await post('/api/workspace/decide', { changeId, decision: 'approved' });

  const applyRes = await post('/api/workspace/apply');
  assert.equal(applyRes.status, 422);
  assert.match(applyRes.body.error.why, /paragraph count changed/);
});

test('GET /api/tasks reflects GRID as the 4th implemented capability', async () => {
  const { status, body } = await get('/api/tasks');
  assert.equal(status, 200);
  assert.equal(body.tasks.filter((t) => t.status === 'implemented').length, 4);
  const grid = body.tasks.find((t) => t.task_id === 'prism-grid');
  assert.equal(grid.status, 'implemented');
});

test('vault undo with no history returns a structured error, not a 500', async () => {
  const res = await post('/api/vault/undo');
  assert.equal(res.status, 409);
});

test('vault revert actually restores the target version\'s content, confirmed via GET /api/vault/graph', async () => {
  const [baseB64, targetB64] = await Promise.all([
    readFile(v1Path).then((b) => b.toString('base64')),
    readFile(v2Path).then((b) => b.toString('base64')),
  ]);

  // Produce two committed versions: apply once, then reset+apply again with
  // different decisions, so there are genuinely two distinct fingerprints.
  const cmp1 = await post('/api/workspace/compare', { baseBase64: baseB64, targetBase64: targetB64 });
  for (const e of cmp1.body.approvalSet) await post('/api/workspace/decide', { changeId: e.changeId, decision: 'approved' });
  const apply1 = await post('/api/workspace/apply');
  const v1 = apply1.body.version;

  const cmp2 = await post('/api/workspace/compare', { baseBase64: baseB64, targetBase64: targetB64 });
  for (const e of cmp2.body.approvalSet) await post('/api/workspace/decide', { changeId: e.changeId, decision: 'rejected' });
  const apply2 = await post('/api/workspace/apply');
  const v2 = apply2.body.version;

  assert.notEqual(v1.fingerprint, v2.fingerprint, 'the two applies must have produced genuinely different content');

  const revertRes = await post('/api/vault/revert', { versionId: v1.versionId });
  assert.equal(revertRes.status, 200);
  assert.equal(revertRes.body.current.fingerprint, v1.fingerprint, 'reverting must restore v1\'s exact fingerprint');

  const graphRes = await get('/api/vault/graph');
  assert.equal(graphRes.body.current.fingerprint, v1.fingerprint);
  assert.equal(graphRes.body.graph.length, 3, 'v1, v2, and the new revert-commit should all exist in the audit graph');
});

test('an "edited" decision through the real HTTP API produces a downloaded docx containing the replacement text', async () => {
  const [baseB64, targetB64] = await Promise.all([
    readFile(v1Path).then((b) => b.toString('base64')),
    readFile(v2Path).then((b) => b.toString('base64')),
  ]);

  const cmp = await post('/api/workspace/compare', { baseBase64: baseB64, targetBase64: targetB64 });
  const ids = cmp.body.approvalSet.map((e) => e.changeId);
  const dateChangeId = cmp.body.approvalSet.find((e) => e.change.findings?.some((f) => f.category === 'date')).changeId;

  const editedText = 'This Agreement commences on a date to be mutually agreed in writing.';
  const editRes = await post('/api/workspace/decide', { changeId: dateChangeId, decision: 'edited', editedText });
  assert.equal(editRes.status, 200);
  assert.equal(editRes.body.approvalSet.find((e) => e.changeId === dateChangeId).decision, 'edited');

  for (const id of ids) {
    if (id !== dateChangeId) await post('/api/workspace/decide', { changeId: id, decision: 'rejected' });
  }

  const applyRes = await post('/api/workspace/apply');
  assert.equal(applyRes.status, 200);
  assert.equal(applyRes.body.contentVerified, true);

  const downloadRes = await fetch(`${baseUrl}/api/workspace/download`);
  const buf = Buffer.from(await downloadRes.arrayBuffer());
  const outPath = path.join(os.tmpdir(), `prism-ui-edit-check-${Date.now()}.docx`);
  await writeFile(outPath, buf);
  const outputDoc = await readDocx(outPath);

  assert.ok(
    outputDoc.paragraphs.some((p) => p.text === editedText),
    'the edited replacement text must appear in the actually-downloaded file, not just the API response',
  );
  assert.ok(
    outputDoc.paragraphs.every((p) => !p.text.includes('January 1, 2026') && !p.text.includes('March 1, 2026')),
    'neither the original nor the proposed date text should remain after an edit',
  );
  await rm(outPath, { force: true });
});
