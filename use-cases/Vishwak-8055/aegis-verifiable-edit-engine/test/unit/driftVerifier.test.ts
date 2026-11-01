import { describe, it, expect } from 'vitest';
import { runDriftVerifier, registerDriftDetector, listDriftDetectors } from '../../src/verification/driftVerifier.js';
import { makeContext } from './testHelpers.js';
import type { Finding } from '../../src/types/verification.js';

describe('runDriftVerifier', () => {
  it('ships with exactly the two documented built-in detectors', () => {
    expect(listDriftDetectors().map((d) => d.name)).toEqual(['textual-drift', 'numeric-drift-rollup']);
  });

  it('flags excessive churn for a broad-scope, low-magnitude edit kind', () => {
    const before = Array.from({ length: 10 }, (_, i) => `Paragraph ${i}.`).join('\n\n');
    const after = Array.from({ length: 10 }, (_, i) => `Paragraph ${i}, rewritten completely differently.`).join('\n\n');
    const ctx = makeContext(before, after, { editKind: 'style-only', scope: { kind: 'style-only' } });
    const outcome = runDriftVerifier(ctx, []);
    expect(outcome.findings.map((f) => f.kind)).toContain('DRIFT_TEXTUAL_EXCESSIVE');
  });

  it('does not flag textual drift for a narrowly-scoped edit (scopeVerifier already owns that)', () => {
    const before = Array.from({ length: 10 }, (_, i) => `Paragraph ${i}.`).join('\n\n');
    const after = Array.from({ length: 10 }, (_, i) => `Paragraph ${i}, rewritten.`).join('\n\n');
    const ctx = makeContext(before, after, { scope: { kind: 'paragraph-index', index: 1 } });
    const outcome = runDriftVerifier(ctx, []);
    expect(outcome.findings.map((f) => f.kind)).not.toContain('DRIFT_TEXTUAL_EXCESSIVE');
  });

  it('summarizes protected-value findings without re-judging them', () => {
    const ctx = makeContext('a', 'a');
    const priorFindings: Finding[] = [
      { id: '1', checker: 'protected_value', kind: 'PROTECTED_VALUE_CURRENCY_CHANGED', confidence: 1, message: 'x' },
      { id: '2', checker: 'protected_value', kind: 'PROTECTED_VALUE_DATE_CHANGED', confidence: 1, message: 'y' },
    ];
    const outcome = runDriftVerifier(ctx, priorFindings);
    const summary = outcome.findings.find((f) => f.kind === 'DRIFT_NUMERIC_SUMMARY');
    expect(summary?.message).toContain('2 protected numeric/date/currency');
  });

  it('supports registering an additional detector without modifying this file', () => {
    const before = listDriftDetectors().length;
    registerDriftDetector({ name: 'test-only-detector', detect: () => [] });
    expect(listDriftDetectors().length).toBe(before + 1);
    // Not removed afterward — registries are process-lifetime by design (see docs). Harmless here since it always returns [].
  });
});
