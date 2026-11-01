import { describe, it, expect } from 'vitest';
import { AegisEngine } from '../../src/orchestrator/aegisEngine.js';
import { MockSuperDocClient } from '../../src/execution/mockSuperDocClient.js';
import { fixedResult } from '../../src/execution/scenarioResolvers.js';
import { Logger } from '../../src/logging/logger.js';

const quietLogger = new Logger('error', false);

/**
 * Every (original value, mutated value) pair below represents ONE protected
 * invariant being silently changed. For every single one, the property
 * under test is: the engine must never end in VERIFIED. It's fine — even
 * expected — for the specific decision to vary (BLOCKED vs REQUIRES_REVIEW
 * depending on severity), but "VERIFIED" would mean Aegis let a silent
 * mutation through, which is the one outcome this system exists to prevent.
 */
const MUTATIONS: { name: string; before: string; after: string }[] = [
  { name: 'currency', before: 'The fee is $250.', after: 'The fee is $999.' },
  { name: 'date', before: 'Due on January 5, 2027.', after: 'Due on January 9, 2027.' },
  { name: 'duration', before: 'Payment must be made within 30 days.', after: 'Payment must be made within 90 days.' },
  { name: 'percentage', before: 'Interest accrues at 1.5% per month.', after: 'Interest accrues at 9.5% per month.' },
  { name: 'obligation-to-permission', before: 'The Supplier shall notify the Customer.', after: 'The Supplier may notify the Customer.' },
  { name: 'prohibition-weakened', before: 'The Customer shall not assign this Agreement.', after: 'The Customer may assign this Agreement.' },
  { name: 'modality-inverted', before: 'The Customer shall pay in advance.', after: 'The Customer shall not pay in advance.' },
  { name: 'url', before: 'See https://example.com/original-terms for detail.', after: 'See https://example.com/different-terms for detail.' },
  { name: 'exception-removed', before: 'No refunds, except within the first 14 days.', after: 'No refunds.' },
  { name: 'table-dimensions', before: '| Item | Price |\n| --- | --- |\n| Widget | $5 |', after: '| Item | Price | Tax |\n| --- | --- | --- |\n| Widget | $5 | $1 |' },
];

describe('property: a protected invariant cannot be silently mutated past verification', () => {
  it.each(MUTATIONS)('$name: mutating it never results in VERIFIED', async ({ before, after }) => {
    const engine = new AegisEngine({
      superDocClient: new MockSuperDocClient({ resolver: fixedResult(after) }),
      logger: quietLogger,
    });
    const result = await engine.runEdit({ document: before, instruction: 'Improve the wording.' });

    expect(result.proof.decision).not.toBe('VERIFIED');
    expect(result.proof.decision).not.toBe('VERIFIED_WITH_WARNINGS');
    expect(result.finalDocument).toBeNull();
    expect(result.proof.evidence.findings.length).toBeGreaterThan(0);
  });

  it('the SAME mutations, when explicitly requested, are allowed through (the property is about SILENT mutation, not all change)', async () => {
    const engine = new AegisEngine({
      superDocClient: new MockSuperDocClient({
        resolver: fixedResult('Payment must be made within 90 days.'),
      }),
      logger: quietLogger,
    });
    const result = await engine.runEdit({
      document: 'Payment must be made within 30 days.',
      instruction: 'Extend the payment deadline to 90 days.',
    });
    expect(result.proof.decision).toBe('VERIFIED');
    expect(result.finalDocument).toBe('Payment must be made within 90 days.');
  });
});
