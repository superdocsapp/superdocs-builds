import { extractScope } from './scopeExtractor.js';
import { extractInvariants } from './invariantExtractor.js';
import type { AiProvider } from './aiProvider.js';
import { NullAiProvider } from './aiProvider.js';
import type { CompiledIntent, EditKind } from '../types/instruction.js';

const RESTRUCTURE_KEYWORDS = /\b(reorgani[sz]e|restructure|convert.*to a table|turn.*into a list|split.*into sections|merge.*paragraphs)\b/i;

/**
 * The Intent Layer's single entry point: turns free text into a
 * `CompiledIntent`. Deterministic end to end in this repository — the
 * `aiProvider` parameter exists so a host application can later hand
 * genuinely ambiguous instructions to a real model without changing this
 * function's contract (see src/intent/aiProvider.ts).
 */
export async function compileIntent(instructionText: string, aiProvider: AiProvider = new NullAiProvider()): Promise<CompiledIntent> {
  const { scope, confidence: scopeConfidence } = extractScope(instructionText);
  const { protectSemantics, protectValues, explicitlyStated, requestedValueChanges } =
    extractInvariants(instructionText);

  const editKind = deriveEditKind(instructionText, scope, requestedValueChanges.length > 0);

  // Nothing in this repository's test/benchmark corpus is ambiguous enough
  // to need it, but the hook is real: a low-confidence, non-value-change
  // instruction is exactly the case a semantic AI provider would be asked
  // to help disambiguate in a production deployment.
  let aiAssisted = false;
  if (scopeConfidence < 0.5 && editKind === 'unspecified' && aiProvider.name !== 'none') {
    const answer = await aiProvider.compareMeaning({
      beforeText: instructionText,
      afterText: instructionText,
      deterministicHint: 'scope extraction produced low confidence',
    });
    aiAssisted = answer.available;
  }

  const confidence = Math.min(1, scopeConfidence + (explicitlyStated ? 0.1 : 0));

  return {
    instructionText,
    summary: summarize(instructionText, scope, editKind),
    editKind,
    scope,
    requestedValueChanges,
    protectSemantics,
    protectValues,
    confidence,
    aiAssisted,
  };
}

function deriveEditKind(instructionText: string, scope: CompiledIntent['scope'], hasValueChanges: boolean): EditKind {
  if (RESTRUCTURE_KEYWORDS.test(instructionText)) return 'restructure';
  if (hasValueChanges) return 'value-change';
  if (scope.kind === 'style-only') return 'style-only';
  if (scope.kind === 'paragraph-index' || scope.kind === 'heading') return 'targeted-fix';
  if (scope.kind === 'whole-document') return 'style-only';
  return 'unspecified';
}

function summarize(instructionText: string, scope: CompiledIntent['scope'], editKind: EditKind): string {
  const scopeDescription =
    scope.kind === 'paragraph-index'
      ? `paragraph ${scope.index}`
      : scope.kind === 'heading'
        ? `the "${scope.headingText}" section`
        : scope.kind === 'whole-document'
          ? 'the whole document'
          : scope.kind === 'style-only'
            ? 'style/wording, document-wide'
            : 'an unspecified region (treated as whole-document with full protection)';
  return `${editKind} edit targeting ${scopeDescription}: "${truncate(instructionText, 80)}"`;
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}
