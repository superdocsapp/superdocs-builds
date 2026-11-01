import { describe, it, expect } from 'vitest';
import { runProtectedValueVerifier } from '../../src/verification/protectedValueVerifier.js';
import { makeContext } from './testHelpers.js';

describe('runProtectedValueVerifier', () => {
  it('flags an unrequested date/duration mutation as HIGH-eligible', () => {
    const ctx = makeContext('Payment must be made within 30 days.', 'Payment must be made within 60 days.');
    const outcome = runProtectedValueVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('PROTECTED_VALUE_DURATION_CHANGED');
  });

  it('flags an unrequested currency mutation', () => {
    const ctx = makeContext('The fee is $250.', 'The fee is $500.');
    const outcome = runProtectedValueVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('PROTECTED_VALUE_CURRENCY_CHANGED');
  });

  it('does NOT flag a value change that was explicitly requested', () => {
    const ctx = makeContext('Payment must be made within 30 days.', 'Payment must be made within 60 days.', {
      requestedValueChanges: [{ raw: 'extend the deadline to 60 days', toValueRaw: '60 days' }],
    });
    const outcome = runProtectedValueVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).not.toContain('PROTECTED_VALUE_DURATION_CHANGED');
    expect(outcome.findings.map((f) => f.kind)).toContain('PROTECTED_VALUE_REQUESTED_CHANGE');
  });

  it('ignores formatting-only numeric differences', () => {
    const ctx = makeContext('The fee is $1,000.00.', 'The fee is $1000.');
    const outcome = runProtectedValueVerifier(ctx);
    expect(outcome.findings).toHaveLength(0);
  });

  it('reports values lost when their entire containing block is deleted', () => {
    const ctx = makeContext('Intro.\n\nThe fee is $250, due within 30 days.\n\nOutro.', 'Intro.\n\nOutro.');
    const outcome = runProtectedValueVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toEqual(
      expect.arrayContaining(['PROTECTED_VALUE_LOST_WITH_BLOCK', 'PROTECTED_VALUE_LOST_WITH_BLOCK']),
    );
  });

  it('produces no violation findings when protectValues is false', () => {
    const ctx = makeContext('The fee is $250.', 'The fee is $500.', { protectValues: false });
    const outcome = runProtectedValueVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).not.toContain('PROTECTED_VALUE_CURRENCY_CHANGED');
  });
});
