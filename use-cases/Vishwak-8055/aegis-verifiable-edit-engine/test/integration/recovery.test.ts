import { describe, it, expect } from 'vitest';
import { AegisEngine } from '../../src/orchestrator/aegisEngine.js';
import { MockSuperDocClient } from '../../src/execution/mockSuperDocClient.js';
import { sequence } from '../../src/execution/scenarioResolvers.js';
import { Logger } from '../../src/logging/logger.js';

const quietLogger = new Logger('error', false);

const DOC = 'Paragraph one.\n\nParagraph two.\n\nParagraph three.';

describe('recovery loop', () => {
  it('recovers on a retry after a scope-escaping first attempt, and commits the second attempt', async () => {
    const engine = new AegisEngine({
      superDocClient: new MockSuperDocClient({
        // Attempt 1 touches paragraph 2 as well as paragraph 3 (out of scope).
        // Attempt 2 (and beyond) only touches paragraph 3, as instructed.
        resolver: sequence([
          'Paragraph one.\n\nParagraph two, unexpectedly touched.\n\nParagraph three fixed.',
          'Paragraph one.\n\nParagraph two.\n\nParagraph three fixed.',
        ]),
      }),
      config: { mode: 'mock', retryBudget: 2, timeoutMs: 10_000, logLevel: 'error', logDocumentContent: false },
      logger: quietLogger,
    });

    const result = await engine.runEdit({ document: DOC, instruction: 'Fix the typo in paragraph 3.' });

    expect(result.proof.decision).toBe('VERIFIED');
    expect(result.proof.execution_metadata.attempts_used).toBe(2);
    expect(result.proof.evidence.attempts).toHaveLength(2);
    expect(result.proof.evidence.attempts[0].decision).toBe('BLOCKED');
    expect(result.proof.evidence.attempts[1].decision).toBe('VERIFIED');
    expect(result.proof.evidence.attempts[1].instructionUsed).toContain('Automated recovery constraint');
    expect(result.finalDocument).toContain('Paragraph three fixed.');
  });

  it('exhausts the retry budget and ends in a non-VERIFIED decision without ever committing a bad result', async () => {
    const engine = new AegisEngine({
      superDocClient: new MockSuperDocClient({
        // Every attempt keeps touching paragraph 2 unexpectedly — never recovers.
        resolver: () => ({ resultDocument: 'Paragraph one.\n\nParagraph two, ALWAYS touched.\n\nParagraph three fixed.' }),
      }),
      config: { mode: 'mock', retryBudget: 2, timeoutMs: 10_000, logLevel: 'error', logDocumentContent: false },
      logger: quietLogger,
    });

    const result = await engine.runEdit({ document: DOC, instruction: 'Fix the typo in paragraph 3.' });

    expect(result.proof.decision).toBe('BLOCKED');
    expect(result.proof.execution_metadata.attempts_used).toBe(3); // 1 original + 2 retries
    expect(result.finalDocument).toBeNull();
    expect(result.proof.evidence.attempts.every((a) => a.decision === 'BLOCKED')).toBe(true);
  });

  it('does NOT retry a non-recoverable finding (e.g. a currency mutation) even when budget remains', async () => {
    const engine = new AegisEngine({
      superDocClient: new MockSuperDocClient({
        resolver: () => ({ resultDocument: 'Paragraph one.\n\nParagraph two.\n\nThe fee is $999, was $250.' }),
      }),
      config: { mode: 'mock', retryBudget: 2, timeoutMs: 10_000, logLevel: 'error', logDocumentContent: false },
      logger: quietLogger,
    });

    const result = await engine.runEdit({
      document: 'Paragraph one.\n\nParagraph two.\n\nThe fee is $250.',
      instruction: 'Fix the grammar.',
    });

    expect(result.proof.execution_metadata.attempts_used).toBe(1); // stopped immediately, no retry attempted
    expect(['BLOCKED', 'REQUIRES_REVIEW']).toContain(result.proof.decision);
  });
});
