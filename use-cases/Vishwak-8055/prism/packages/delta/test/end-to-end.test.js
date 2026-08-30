import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { compareFiles } from '../src/index.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const v1Path = path.join(__dirname, '..', 'fixtures', 'contract-v1.docx');
const v2Path = path.join(__dirname, '..', 'fixtures', 'contract-v2.docx');

test('end-to-end: real fixture pair produces exactly the expected change profile', async () => {
  const report = await compareFiles(v1Path, v2Path);
  assert.equal(report.summary.hasChanges, true);
  assert.equal(report.summary.totalChanges, 5);
  assert.equal(report.summary.materialChangeCount, 2);
  assert.equal(report.summary.reviewRequiredCount, 2);
  assert.equal(report.summary.cosmeticOnlyCount, 1);
});

test('end-to-end: comparing a document to itself reports no changes', async () => {
  const report = await compareFiles(v1Path, v1Path);
  assert.equal(report.summary.hasChanges, false);
  assert.equal(report.baseFingerprint, report.targetFingerprint);
});
