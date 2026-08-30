import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { compareFiles } from '@prism/delta';
import { createApprovalSet, decide, summarize, applyApprovedChanges } from '../src/index.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const v1Path = path.join(__dirname, '..', '..', 'delta', 'fixtures', 'contract-v1.docx');
const v2Path = path.join(__dirname, '..', '..', 'delta', 'fixtures', 'contract-v2.docx');

function tmp(name) {
  return path.join(os.tmpdir(), `prism-gate-${name}-${Date.now()}-${Math.random().toString(36).slice(2)}.docx`);
}

test('approving every change reproduces the target document', async () => {
  const report = await compareFiles(v1Path, v2Path);
  const approvalSet = createApprovalSet(report);
  for (const changeId of approvalSet.decisions.keys()) decide(approvalSet, changeId, 'approved');
  assert.deepEqual(summarize(approvalSet), { total: 5, approved: 5, rejected: 0, edited: 0, pending: 0 });

  const outPath = tmp('full-approve');
  await applyApprovedChanges(report, approvalSet, outPath);

  const diffAgainstTarget = await compareFiles(outPath, v2Path);
  assert.equal(diffAgainstTarget.summary.hasChanges, false, 'fully-approved output must exactly equal the target');
});

test('rejecting every change reproduces the base document unchanged', async () => {
  const report = await compareFiles(v1Path, v2Path);
  const approvalSet = createApprovalSet(report);
  for (const changeId of approvalSet.decisions.keys()) decide(approvalSet, changeId, 'rejected');

  const outPath = tmp('full-reject');
  await applyApprovedChanges(report, approvalSet, outPath);

  const diffAgainstBase = await compareFiles(outPath, v1Path);
  assert.equal(diffAgainstBase.summary.hasChanges, false, 'fully-rejected output must exactly equal the base');
});

test('partial approval applies exactly the approved subset — verified both directly and by re-diffing', async () => {
  const report = await compareFiles(v1Path, v2Path);
  const approvalSet = createApprovalSet(report);

  // Approve only the numeric (fee) change; reject everything else,
  // including out-of-order (decide id 5 before id 1) to exercise that path.
  const ids = [...approvalSet.decisions.keys()];
  const numericChangeId = ids.find((id) => approvalSet.decisions.get(id).change.findings?.some((f) => f.category === 'numeric'));
  assert.ok(numericChangeId, 'fixture must contain a numeric change');

  decide(approvalSet, ids[4], 'rejected'); // out-of-order: last id first
  decide(approvalSet, numericChangeId, 'approved');
  for (const id of ids) {
    if (id !== numericChangeId) decide(approvalSet, id, 'rejected'); // repeated decision on ids[4] is fine
  }
  assert.deepEqual(summarize(approvalSet), { total: 5, approved: 1, rejected: 4, edited: 0, pending: 0 });

  const outPath = tmp('partial');
  const result = await applyApprovedChanges(report, approvalSet, outPath);
  assert.equal(result.finalParagraphCount, 10, 'base paragraph count — governing law addition was rejected, so no growth');

  // Re-run PRISM DELTA on (output vs base): should show exactly ONE change (the approved numeric one).
  const diffFromBase = await compareFiles(outPath, v1Path);
  assert.equal(diffFromBase.summary.totalChanges, 1);
  assert.equal(diffFromBase.changes[0].findings[0].category, 'numeric');

  // Re-run PRISM DELTA on (output vs target): should show exactly FOUR remaining differences (the rejected ones).
  const diffFromTarget = await compareFiles(outPath, v2Path);
  assert.equal(diffFromTarget.summary.totalChanges, 4, 'the four rejected changes should still differ from target');
});

test('an edited decision uses the human-supplied replacement, not base or target', async () => {
  const report = await compareFiles(v1Path, v2Path);
  const approvalSet = createApprovalSet(report);
  const ids = [...approvalSet.decisions.keys()];
  const dateChangeId = ids.find((id) => approvalSet.decisions.get(id).change.findings?.some((f) => f.category === 'date'));

  const customParagraph = {
    text: 'This Agreement commences on a date to be mutually agreed in writing.',
    styleId: null,
    runs: [{ text: 'This Agreement commences on a date to be mutually agreed in writing.', bold: false, italic: false, underline: false }],
  };
  decide(approvalSet, dateChangeId, 'edited', { editedParagraphs: [customParagraph] });
  for (const id of ids) if (id !== dateChangeId) decide(approvalSet, id, 'rejected');

  const outPath = tmp('edited');
  await applyApprovedChanges(report, approvalSet, outPath);
  const output = await import('@prism/core').then((m) => m.readDocx(outPath));
  const found = output.paragraphs.some((p) => p.text.includes('mutually agreed in writing'));
  assert.ok(found, 'edited replacement text must appear in the written document');
  const oldDateGone = output.paragraphs.every((p) => !p.text.includes('January 1, 2026') && !p.text.includes('March 1, 2026'));
  assert.ok(oldDateGone, 'neither the original nor proposed date text should remain after an edit');
});

test('applying with pending decisions is refused, not silently defaulted', async () => {
  const report = await compareFiles(v1Path, v2Path);
  const approvalSet = createApprovalSet(report);
  // decide only 4 of 5
  const ids = [...approvalSet.decisions.keys()];
  ids.slice(0, 4).forEach((id) => decide(approvalSet, id, 'rejected'));

  await assert.rejects(
    () => applyApprovedChanges(report, approvalSet, tmp('pending')),
    /still pending/,
  );
});
