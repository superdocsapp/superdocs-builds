import { describe, it, expect } from 'vitest';
import { runSemanticVerifier } from '../../src/verification/semanticVerifier.js';
import { makeContext } from './testHelpers.js';

describe('runSemanticVerifier', () => {
  it('flags shall -> may as SEMANTIC_OBLIGATION_TO_PERMISSION', () => {
    const ctx = makeContext('The Supplier shall deliver the goods.', 'The Supplier may deliver the goods.');
    const outcome = runSemanticVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('SEMANTIC_OBLIGATION_TO_PERMISSION');
  });

  it('flags shall <-> shall not as SEMANTIC_MODALITY_INVERTED', () => {
    const ctx = makeContext('The Customer shall pay the deposit.', 'The Customer shall not pay the deposit.');
    const outcome = runSemanticVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('SEMANTIC_MODALITY_INVERTED');
  });

  it('flags may -> shall as SEMANTIC_MODALITY_TIGHTENED, not as a critical finding', () => {
    const ctx = makeContext('The Customer may audit the books.', 'The Customer shall audit the books.');
    const outcome = runSemanticVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('SEMANTIC_MODALITY_TIGHTENED');
  });

  it('does not flag a same-modality rewording', () => {
    const ctx = makeContext(
      'The Supplier shall notify the Customer immediately of any anticipated delay.',
      'The Supplier shall notify the Customer right away about any expected delay.',
    );
    const outcome = runSemanticVerifier(ctx);
    expect(outcome.findings).toHaveLength(0);
  });

  it('flags a removed exception clause', () => {
    const ctx = makeContext(
      'The Customer may not terminate early, except in the case of material breach.',
      'The Customer may not terminate early.',
    );
    const outcome = runSemanticVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('SEMANTIC_CONDITION_OR_EXCEPTION_REMOVED');
  });

  it('flags a changed actor on an otherwise-identical obligation', () => {
    const ctx = makeContext('The Supplier shall pay all shipping costs.', 'The Customer shall pay all shipping costs.');
    const outcome = runSemanticVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('SEMANTIC_ACTOR_CHANGED');
  });

  it('produces no findings at all when protectSemantics is false', () => {
    const ctx = makeContext('The Supplier shall deliver the goods.', 'The Supplier may deliver the goods.', {
      protectSemantics: false,
    });
    const outcome = runSemanticVerifier(ctx);
    expect(outcome.findings).toHaveLength(0);
  });
});
