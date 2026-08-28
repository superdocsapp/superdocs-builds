import { parsePseudoMarkdown, alignBlocks } from '../../src/verification/normalize.js';
import type { VerificationContext } from '../../src/types/context.js';
import type { CompiledIntent } from '../../src/types/instruction.js';

export function makeIntent(overrides: Partial<CompiledIntent> = {}): CompiledIntent {
  return {
    instructionText: overrides.instructionText ?? 'Edit the document.',
    summary: 'test intent',
    editKind: 'unspecified',
    scope: { kind: 'whole-document' },
    requestedValueChanges: [],
    protectSemantics: true,
    protectValues: true,
    confidence: 0.9,
    aiAssisted: false,
    ...overrides,
  };
}

export function makeContext(beforeText: string, afterText: string, intentOverrides: Partial<CompiledIntent> = {}): VerificationContext {
  const before = parsePseudoMarkdown(beforeText);
  const after = parsePseudoMarkdown(afterText);
  const alignment = alignBlocks(before.blocks, after.blocks);
  return { before, after, alignment, intent: makeIntent(intentOverrides) };
}
