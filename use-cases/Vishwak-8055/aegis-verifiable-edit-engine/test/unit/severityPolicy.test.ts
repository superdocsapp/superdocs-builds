import { describe, it, expect } from 'vitest';
import { loadPolicy } from '../../src/risk/severityPolicy.js';

describe('loadPolicy', () => {
  it('classifies a known finding kind from the default policy', () => {
    const policy = loadPolicy();
    expect(policy.classify('SEMANTIC_OBLIGATION_TO_PERMISSION')).toEqual({ severity: 'CRITICAL', recoverable: false });
    expect(policy.classify('FORMATTING_ONLY_CHANGE')).toEqual({ severity: 'LOW', recoverable: true });
  });

  it('falls back to the documented default for an unknown finding kind', () => {
    const policy = loadPolicy();
    expect(policy.classify('SOME_KIND_NOBODY_REGISTERED')).toEqual({ severity: 'MEDIUM', recoverable: true });
  });

  it('applies a safe override that does not downgrade a non-downgradable kind', () => {
    const policy = loadPolicy({ findings: { STRUCTURAL_BLOCK_INSERTED: { severity: 'HIGH' } } });
    expect(policy.classify('STRUCTURAL_BLOCK_INSERTED').severity).toBe('HIGH');
    expect(policy.rejectedOverrides).toHaveLength(0);
  });

  it('REJECTS an attempt to downgrade a non-downgradable finding kind and records it', () => {
    const policy = loadPolicy({ findings: { SEMANTIC_OBLIGATION_TO_PERMISSION: { severity: 'LOW' } } });
    expect(policy.classify('SEMANTIC_OBLIGATION_TO_PERMISSION').severity).toBe('CRITICAL');
    expect(policy.rejectedOverrides).toHaveLength(1);
    expect(policy.rejectedOverrides[0]).toMatchObject({
      kind: 'SEMANTIC_OBLIGATION_TO_PERMISSION',
      attemptedSeverity: 'LOW',
      enforcedSeverity: 'CRITICAL',
    });
  });

  it('rejects a downgrade attempt on every non-downgradable kind, not just semantic ones', () => {
    const policy = loadPolicy({
      findings: {
        PROTECTED_VALUE_CURRENCY_CHANGED: { severity: 'INFO' },
        UNINTENDED_SCOPE_CHANGE: { severity: 'LOW' },
      },
    });
    expect(policy.classify('PROTECTED_VALUE_CURRENCY_CHANGED').severity).toBe('HIGH');
    expect(policy.classify('UNINTENDED_SCOPE_CHANGE').severity).toBe('CRITICAL');
    expect(policy.rejectedOverrides).toHaveLength(2);
  });
});
