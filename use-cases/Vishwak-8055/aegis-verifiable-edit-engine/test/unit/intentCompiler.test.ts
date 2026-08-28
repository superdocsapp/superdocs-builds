import { describe, it, expect } from 'vitest';
import { compileIntent } from '../../src/intent/intentCompiler.js';

describe('compileIntent', () => {
  it('extracts a paragraph-index scope', async () => {
    const intent = await compileIntent('Please fix the grammar in paragraph 4.');
    expect(intent.scope).toEqual({ kind: 'paragraph-index', index: 4 });
    expect(intent.editKind).toBe('targeted-fix');
  });

  it('extracts a heading scope from quoted heading text', async () => {
    const intent = await compileIntent('Simplify the "Termination" section.');
    expect(intent.scope).toEqual({ kind: 'heading', headingText: 'Termination' });
  });

  it('defaults to full protection with an unscoped, low-confidence instruction', async () => {
    const intent = await compileIntent('make it better');
    expect(intent.scope).toEqual({ kind: 'unscoped' });
    expect(intent.protectSemantics).toBe(true);
    expect(intent.protectValues).toBe(true);
    expect(intent.confidence).toBeLessThan(0.5);
  });

  it('recognizes an explicit meaning-preservation instruction as style-only, whole-document scope', async () => {
    const intent = await compileIntent('Make this contract easier to read without changing its legal meaning.');
    expect(intent.scope).toEqual({ kind: 'style-only' });
    expect(intent.protectSemantics).toBe(true);
    expect(intent.protectValues).toBe(true);
  });

  it('records an explicitly requested value change instead of leaving it protected', async () => {
    const intent = await compileIntent('Extend the payment deadline to 60 days.');
    expect(intent.editKind).toBe('value-change');
    expect(intent.requestedValueChanges.length).toBeGreaterThan(0);
    expect(intent.requestedValueChanges[0].toValueRaw).toMatch(/60 days/);
  });

  it('releases value protection only when explicitly told to', async () => {
    const intent = await compileIntent('Rewrite this however you like, you can change the numbers and dates.');
    expect(intent.protectValues).toBe(false);
    expect(intent.protectSemantics).toBe(true);
  });
});
