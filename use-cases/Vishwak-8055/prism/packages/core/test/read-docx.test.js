import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readDocx } from '../src/docx/read-docx.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const v1Path = path.join(__dirname, '..', '..', 'delta', 'fixtures', 'contract-v1.docx');
const v2Path = path.join(__dirname, '..', '..', 'delta', 'fixtures', 'contract-v2.docx');

test('readDocx extracts the expected paragraph count for each fixture', async () => {
  const v1 = await readDocx(v1Path);
  const v2 = await readDocx(v2Path);
  // v1: title + intro + (heading + body) x4 = 10
  assert.equal(v1.paragraphs.length, 10);
  // v2: same as v1 plus (heading + body) for the new Governing Law section = 12
  assert.equal(v2.paragraphs.length, 12);
});

test('readDocx concatenates run text and finds known content', async () => {
  const v1 = await readDocx(v1Path);
  const feePara = v1.paragraphs.find((p) => p.text.includes('total contract price'));
  assert.ok(feePara, 'fee paragraph should be found');
  assert.match(feePara.text, /\$50,000/);
  assert.match(feePara.text, /30 days/);
});

test('readDocx marks heading paragraphs via styleId', async () => {
  const v1 = await readDocx(v1Path);
  const heading1 = v1.paragraphs.find((p) => p.text === 'SERVICES AGREEMENT');
  assert.ok(heading1.isHeading, 'title should be detected as a heading');
  const sectionHeading = v1.paragraphs.find((p) => p.text === '1. Fees');
  assert.ok(sectionHeading.isHeading, 'section heading should be detected as a heading');
  const bodyPara = v1.paragraphs.find((p) => p.text.includes('total contract price'));
  assert.equal(bodyPara.isHeading, false);
});

test('readDocx captures run-level bold formatting', async () => {
  const v1 = await readDocx(v1Path);
  const v2 = await readDocx(v2Path);
  const notices1 = v1.paragraphs.find((p) => p.text.includes('All notices'));
  const notices2 = v2.paragraphs.find((p) => p.text.includes('All notices'));
  assert.equal(notices1.runs[0].bold, false);
  assert.equal(notices2.runs[0].bold, true);
  // and the text itself is identical — this pairing is a pure formatting change
  assert.equal(notices1.text, notices2.text);
});
