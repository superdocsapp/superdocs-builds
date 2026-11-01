import { describe, it, expect } from 'vitest';
import { AegisEngine } from '../../src/orchestrator/aegisEngine.js';
import { MockSuperDocClient } from '../../src/execution/mockSuperDocClient.js';
import { fixedResult } from '../../src/execution/scenarioResolvers.js';
import { stableHash } from '../../src/evidence/serialize.js';
import { Logger } from '../../src/logging/logger.js';

const quietLogger = new Logger('error', false);

const CONTRACT = `# Agreement

## Delivery

The Supplier shall deliver the goods within 30 days of the order date.

## Payment

Payment must be made within 30 days of the invoice date.
`;

describe('AegisEngine.runEdit — end to end against the mock adapter', () => {
  it('VERIFIES a safe, meaning-preserving rewrite and commits it', async () => {
    const engine = new AegisEngine({
      superDocClient: new MockSuperDocClient({
        resolver: fixedResult(CONTRACT.replace('Payment must be made within 30 days', 'Payment shall be made within 30 days')),
      }),
      logger: quietLogger,
    });
    const result = await engine.runEdit({
      document: CONTRACT,
      instruction: 'Make this contract easier to read without changing its legal meaning.',
    });

    expect(result.proof.decision).toBe('VERIFIED');
    expect(result.finalDocument).not.toBeNull();
    expect(result.pendingReviewDocument).toBeNull();
    expect(result.proof.execution_metadata.final_receipt_status).toBe('applied');
    expect(result.proof.verification_results).toHaveLength(6);
    expect(result.proof.evidence.proof_hash).toMatch(/^[0-9a-f]+$/);
  });

  it('BLOCKS a dangerous obligation-to-permission mutation and does not commit it', async () => {
    const engine = new AegisEngine({
      superDocClient: new MockSuperDocClient({
        resolver: fixedResult(CONTRACT.replace('The Supplier shall deliver', 'The Supplier may deliver')),
      }),
      logger: quietLogger,
    });
    const result = await engine.runEdit({
      document: CONTRACT,
      instruction: 'Make this contract easier to read without changing its legal meaning.',
    });

    expect(result.proof.decision).toBe('BLOCKED');
    expect(result.finalDocument).toBeNull();
    expect(result.proof.execution_metadata.final_receipt_status).toBe('rejected');
    expect(result.proof.risk_assessment.highest_severity).toBe('CRITICAL');
    const critical = result.proof.evidence.findings.find((f) => f.kind === 'SEMANTIC_OBLIGATION_TO_PERMISSION');
    expect(critical).toBeDefined();
    expect(critical?.before).toContain('shall deliver');
    expect(critical?.after).toContain('may deliver');
  });

  it('BLOCKS an unrequested currency mutation', async () => {
    const withFee = CONTRACT.replace('within 30 days of the invoice date.', 'within 30 days of the invoice date, plus a $250 fee.');
    const mutated = withFee.replace('$250 fee', '$999 fee');
    const engine = new AegisEngine({ superDocClient: new MockSuperDocClient({ resolver: fixedResult(mutated) }), logger: quietLogger });
    const result = await engine.runEdit({ document: withFee, instruction: 'Fix the punctuation in this contract.' });

    expect(['BLOCKED', 'REQUIRES_REVIEW']).toContain(result.proof.decision);
    expect(result.proof.evidence.findings.map((f) => f.kind)).toContain('PROTECTED_VALUE_CURRENCY_CHANGED');
  });

  it('requires human review (does not auto-commit) for an unscoped structural insertion', async () => {
    const engine = new AegisEngine({
      superDocClient: new MockSuperDocClient({
        resolver: fixedResult(`${CONTRACT}\n## New Section\n\nSomething nobody asked for.\n`),
      }),
      logger: quietLogger,
    });
    const result = await engine.runEdit({ document: CONTRACT, instruction: 'Fix the grammar in paragraph 1.' });

    // A structural insertion under a narrow paragraph-scope is a scope
    // violation (CRITICAL) as well as a structural one — CRITICAL wins.
    expect(result.proof.decision).toBe('BLOCKED');
    expect(result.finalDocument).toBeNull();
  });

  it('proof_hash is a genuine self-check: recomputing it from the stored proof reproduces the same value (tamper-evidence)', async () => {
    const engine = new AegisEngine({
      superDocClient: new MockSuperDocClient({ resolver: fixedResult(CONTRACT) }),
      idGenerator: () => 'fixed-id',
      logger: quietLogger,
    });
    const { proof } = await engine.runEdit({ document: CONTRACT, instruction: 'Fix the grammar in paragraph 1.' });

    // This mirrors exactly what buildEditProof() does internally — see
    // src/evidence/editProof.ts. A verifier re-checking a *stored* proof
    // would do the same thing to confirm nothing in it was edited after
    // the fact. (Two separate live runEdit() calls are NOT expected to
    // match: each carries its own real timestamp/duration, which is
    // correct for an audit trail — see docs/ARCHITECTURE.md "EditProof".)
    const recomputed = stableHash({ ...proof, evidence: { ...proof.evidence, proof_hash: undefined } });
    expect(recomputed).toBe(proof.evidence.proof_hash);
  });
});
