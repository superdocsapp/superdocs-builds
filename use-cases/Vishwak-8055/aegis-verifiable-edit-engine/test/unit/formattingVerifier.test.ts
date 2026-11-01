import { describe, it, expect } from 'vitest';
import { runFormattingVerifier } from '../../src/verification/formattingVerifier.js';
import { makeContext } from './testHelpers.js';

describe('runFormattingVerifier', () => {
  it('flags a pure emphasis-only change as FORMATTING_ONLY_CHANGE', () => {
    const outcome = runFormattingVerifier(makeContext('The fee is $250.', 'The fee is **$250**.'));
    expect(outcome.findings.map((f) => f.kind)).toContain('FORMATTING_ONLY_CHANGE');
  });

  it('does not flag a real content change as formatting-only', () => {
    const outcome = runFormattingVerifier(makeContext('The fee is $250.', 'The fee is $500.'));
    expect(outcome.findings.map((f) => f.kind)).not.toContain('FORMATTING_ONLY_CHANGE');
  });

  it('flags an unbalanced emphasis marker introduced by the edit', () => {
    const outcome = runFormattingVerifier(makeContext('The fee is $250.', 'The fee is **$250.'));
    expect(outcome.findings.map((f) => f.kind)).toContain('FORMATTING_MARKER_UNBALANCED');
  });
});
