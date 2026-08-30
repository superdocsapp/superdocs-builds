import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  classifyModifiedParagraph,
  classifyCommonPair,
  classifyStructuralBlock,
} from '../src/classify/classify-change.js';

function para(index, text, runs) {
  return { index, text, styleId: null, runs: runs ?? [{ text, bold: false, italic: false, underline: false }] };
}

test('classifyModifiedParagraph detects a numeric change as material', () => {
  const result = classifyModifiedParagraph(
    para(0, 'The total contract price is $50,000, payable within 30 days of invoice.'),
    para(0, 'The total contract price is $65,000, payable within 15 days of invoice.'),
  );
  const finding = result.findings.find((f) => f.category === 'numeric');
  assert.ok(finding, 'should detect a numeric finding');
  assert.equal(finding.materiality, 'material');
});

test('classifyModifiedParagraph treats a small (<2%) numeric delta as minor, not material', () => {
  const result = classifyModifiedParagraph(para(0, 'The fee is 100.'), para(0, 'The fee is 101.'));
  const finding = result.findings.find((f) => f.category === 'numeric');
  assert.ok(finding);
  assert.equal(finding.materiality, 'minor');
});

test('classifyModifiedParagraph detects a date change even when only the month token differs', () => {
  const result = classifyModifiedParagraph(
    para(0, 'This Agreement commences on January 1, 2026 and continues for twelve (12) months.'),
    para(0, 'This Agreement commences on March 1, 2026 and continues for twelve (12) months.'),
  );
  const finding = result.findings.find((f) => f.category === 'date');
  assert.ok(finding, 'should detect a date finding even though day/year tokens are unchanged');
  assert.equal(finding.materiality, 'material');
  // and must NOT also fire a numeric finding just because "12" appears unchanged in both
  const numericFinding = result.findings.find((f) => f.category === 'numeric');
  assert.equal(numericFinding, undefined, 'unchanged "(12)" must not be misread as a numeric change');
});

test('classifyModifiedParagraph flags obligation-language changes for review, without scoring materiality itself', () => {
  const result = classifyModifiedParagraph(
    para(0, 'The Contractor shall use reasonable efforts to protect Confidential Information.'),
    para(
      0,
      'The Contractor shall use best efforts to protect Confidential Information and shall indemnify the Company for any breach.',
    ),
  );
  const finding = result.findings.find((f) => f.category === 'semantic');
  assert.ok(finding);
  assert.equal(finding.materiality, 'review-required');
});

test('classifyModifiedParagraph falls back honestly when no deterministic rule matches', () => {
  const result = classifyModifiedParagraph(
    para(0, 'The sky was clear that morning.'),
    para(0, 'The clouds gathered before noon.'),
  );
  assert.equal(result.findings.length, 1);
  assert.equal(result.findings[0].category, 'semantic');
  assert.equal(result.findings[0].materiality, 'review-required');
});

test('classifyCommonPair detects a formatting-only change (identical text, different bold)', () => {
  const base = para(0, 'All notices must be in writing.', [
    { text: 'All notices must be in writing.', bold: false, italic: false, underline: false },
  ]);
  const target = para(0, 'All notices must be in writing.', [
    { text: 'All notices must be in writing.', bold: true, italic: false, underline: false },
  ]);
  const result = classifyCommonPair(base, target);
  assert.ok(result, 'formatting difference should be detected');
  assert.equal(result.findings[0].category, 'formatting');
  assert.equal(result.findings[0].materiality, 'cosmetic');
});

test('classifyCommonPair returns null when nothing actually changed', () => {
  const base = para(0, 'Identical text.');
  const target = para(0, 'Identical text.');
  assert.equal(classifyCommonPair(base, target), null);
});

test('classifyStructuralBlock flags added paragraphs for review rather than guessing their materiality', () => {
  const result = classifyStructuralBlock('added', [para(0, '5. Governing Law'), para(1, 'Delaware law applies.')]);
  assert.equal(result.type, 'structural-add');
  assert.equal(result.findings[0].materiality, 'review-required');
  assert.equal(result.items.length, 2);
});
