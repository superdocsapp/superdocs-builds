import type { RequestedValueChange } from '../types/instruction.js';

const MEANING_PROTECTION_PATTERN =
  /\bwithout\s+changing\s+(?:its|the)\s+(?:legal\s+)?meaning\b|\bpreserve\s+(?:the\s+)?meaning\b|\bdo(?:n't| not)\s+change\s+(?:the\s+)?meaning\b|\bkeep\s+the\s+(?:legal\s+)?(?:meaning|terms|obligations)\s+(?:the\s+same|intact|unchanged)\b/i;

const MEANING_RELEASE_PATTERN =
  /\byou\s+(?:can|may)\s+change\s+(?:the\s+)?meaning\b|\bmeaning\s+(?:can|may)\s+change\b|\bfeel free to (?:change|alter) the (?:meaning|terms)\b/i;

const VALUE_RELEASE_PATTERN =
  /\byou\s+(?:can|may)\s+(?:also\s+)?(?:change|update|adjust)\s+(?:the\s+)?(?:numbers|dates|prices|values|amounts)\b/i;

/**
 * Matches "<verb> ... to <value>" so an explicitly requested numeric/date
 * change is recorded as *permitted* rather than flagged as a protected-value
 * violation later. See src/verification/protectedValueVerifier.ts.
 */
// Alternatives are ordered most-specific-first: regex alternation takes the
// first branch that matches at a given position, so "60 days" must be tried
// before the bare-number branch or it would only ever capture "60".
const REQUESTED_CHANGE_PATTERN =
  /\b(?:change|update|extend|reduce|increase|decrease|make|move|shift|set)\b[^.;\n]{0,80}?\bto\s+(\d+\s?(?:days?|weeks?|months?|years?|hours?)\b|[A-Za-z]+ \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2}|\$?\d[\d,]*(?:\.\d+)?%?)/gi;

export interface InvariantExtraction {
  protectSemantics: boolean;
  protectValues: boolean;
  /** True when the instruction said so explicitly (e.g. "without changing its legal meaning"), for confidence scoring — not for the boolean above, which defaults to protective either way. */
  explicitlyStated: boolean;
  requestedValueChanges: RequestedValueChange[];
}

export function extractInvariants(instructionText: string): InvariantExtraction {
  const explicitProtect = MEANING_PROTECTION_PATTERN.test(instructionText);
  const explicitRelease = MEANING_RELEASE_PATTERN.test(instructionText);
  const valueRelease = VALUE_RELEASE_PATTERN.test(instructionText);

  // Safe default: protect everything unless the instruction explicitly says
  // otherwise. An explicit "preserve meaning" phrase (`explicitProtect`)
  // doesn't change the boolean — it's already the default — but confirms
  // the default was actually the caller's intent when both extractInvariants
  // and extractScope produced their picture from the same sentence, so
  // intentCompiler.ts folds it into the confidence score instead.
  const protectSemantics = !explicitRelease;
  const protectValues = !valueRelease;

  const requestedValueChanges: RequestedValueChange[] = [];
  for (const match of instructionText.matchAll(REQUESTED_CHANGE_PATTERN)) {
    requestedValueChanges.push({ raw: match[0].trim(), toValueRaw: match[1] });
  }

  return { protectSemantics, protectValues, explicitlyStated: explicitProtect, requestedValueChanges };
}
