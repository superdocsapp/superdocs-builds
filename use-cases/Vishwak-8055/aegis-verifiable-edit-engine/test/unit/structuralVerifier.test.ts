import { describe, it, expect } from 'vitest';
import { runStructuralVerifier } from '../../src/verification/structuralVerifier.js';
import { makeContext } from './testHelpers.js';

describe('runStructuralVerifier', () => {
  it('flags a deleted paragraph', () => {
    const ctx = makeContext('Keep this.\n\nDelete this one.\n\nKeep this too.', 'Keep this.\n\nKeep this too.');
    const outcome = runStructuralVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('STRUCTURAL_BLOCK_DELETED');
  });

  it('flags an inserted paragraph', () => {
    const ctx = makeContext('Keep this.', 'Keep this.\n\nA brand new sentence.');
    const outcome = runStructuralVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('STRUCTURAL_BLOCK_INSERTED');
  });

  it('flags a heading level change', () => {
    const ctx = makeContext('# Title\n\nBody.', '## Title\n\nBody.');
    const outcome = runStructuralVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('STRUCTURAL_HEADING_LEVEL_CHANGED');
  });

  it('flags a table dimension change', () => {
    const before = '| a | b |\n| --- | --- |\n| 1 | 2 |';
    const after = '| a | b | c |\n| --- | --- | --- |\n| 1 | 2 | 3 |';
    const outcome = runStructuralVerifier(makeContext(before, after));
    expect(outcome.findings.map((f) => f.kind)).toContain('STRUCTURAL_TABLE_DIMENSION_CHANGED');
  });

  it('flags a link whose URL changed', () => {
    const before = 'See the [policy](https://example.com/v1) for detail.';
    const after = 'See the [policy](https://malicious.example/v2) for detail.';
    const outcome = runStructuralVerifier(makeContext(before, after));
    expect(outcome.findings.map((f) => f.kind)).toContain('STRUCTURAL_LINK_URL_CHANGED');
  });

  it('does not flag anything for an untouched document', () => {
    const outcome = runStructuralVerifier(makeContext('Same.\n\nSame again.', 'Same.\n\nSame again.'));
    expect(outcome.findings).toHaveLength(0);
  });
});
