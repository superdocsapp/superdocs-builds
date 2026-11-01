import { describe, it, expect } from 'vitest';
import { runScopeVerifier } from '../../src/verification/scopeVerifier.js';
import { makeContext } from './testHelpers.js';

const DOC_BEFORE = 'Paragraph one.\n\nParagraph two.\n\nParagraph three.\n\nParagraph four has a typo.';

describe('runScopeVerifier', () => {
  it('allows an in-scope change to the named paragraph', () => {
    const ctx = makeContext(DOC_BEFORE, 'Paragraph one.\n\nParagraph two.\n\nParagraph three.\n\nParagraph four is fixed.', {
      scope: { kind: 'paragraph-index', index: 4 },
    });
    const outcome = runScopeVerifier(ctx);
    expect(outcome.findings).toHaveLength(0);
  });

  it('flags a change to a paragraph outside the named scope', () => {
    const ctx = makeContext(DOC_BEFORE, 'Paragraph one changed.\n\nParagraph two.\n\nParagraph three.\n\nParagraph four has a typo.', {
      scope: { kind: 'paragraph-index', index: 4 },
    });
    const outcome = runScopeVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('UNINTENDED_SCOPE_CHANGE');
  });

  it('flags an insertion when a narrow scope is set', () => {
    const ctx = makeContext(DOC_BEFORE, `${DOC_BEFORE}\n\nA brand new paragraph.`, {
      scope: { kind: 'paragraph-index', index: 4 },
    });
    const outcome = runScopeVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toContain('UNINTENDED_SCOPE_CHANGE');
  });

  it('reports SCOPE_TARGET_NOT_FOUND and treats every change as out of scope when the named paragraph does not exist', () => {
    const ctx = makeContext('Only one paragraph here.', 'Only one paragraph, edited.', {
      scope: { kind: 'paragraph-index', index: 9 },
    });
    const outcome = runScopeVerifier(ctx);
    expect(outcome.findings.map((f) => f.kind)).toEqual(
      expect.arrayContaining(['SCOPE_TARGET_NOT_FOUND', 'UNINTENDED_SCOPE_CHANGE']),
    );
  });

  it('does not restrict scope for a whole-document intent', () => {
    const ctx = makeContext(DOC_BEFORE, 'Paragraph one changed.\n\nParagraph two changed too.\n\nParagraph three.\n\nParagraph four has a typo.', {
      scope: { kind: 'whole-document' },
    });
    const outcome = runScopeVerifier(ctx);
    expect(outcome.findings).toHaveLength(0);
  });

  it('restricts scope to a named heading section only', () => {
    const before = '# Intro\n\nIntro text.\n\n# Payment\n\nPay within 30 days.\n\n# Termination\n\nEither party may terminate.';
    const afterInScope = '# Intro\n\nIntro text.\n\n# Payment\n\nPay within 45 days.\n\n# Termination\n\nEither party may terminate.';
    const afterOutOfScope = '# Intro\n\nIntro text changed.\n\n# Payment\n\nPay within 30 days.\n\n# Termination\n\nEither party may terminate.';

    const inScopeOutcome = runScopeVerifier(makeContext(before, afterInScope, { scope: { kind: 'heading', headingText: 'Payment' } }));
    expect(inScopeOutcome.findings).toHaveLength(0);

    const outOfScopeOutcome = runScopeVerifier(makeContext(before, afterOutOfScope, { scope: { kind: 'heading', headingText: 'Payment' } }));
    expect(outOfScopeOutcome.findings.map((f) => f.kind)).toContain('UNINTENDED_SCOPE_CHANGE');
  });
});
