import type { MockEditResolver } from './mockSuperDocClient.js';

/** Always proposes the same fixed document, regardless of instruction or attempt number. */
export function fixedResult(resultDocument: string): MockEditResolver {
  return () => ({ resultDocument });
}

/**
 * Proposes a different fixed document per attempt (1-based); the final
 * entry repeats for any further attempts. Used to script "the first attempt
 * is unsafe, a constrained retry is safe" recovery scenarios.
 */
export function sequence(results: string[]): MockEditResolver {
  return ({ attempt }) => ({ resultDocument: results[Math.min(attempt, results.length) - 1] });
}

/** A plain string substitution over the original content, ignoring instruction text. Handy for small, surgical benchmark cases. */
export function textReplace(from: string, to: string): MockEditResolver {
  return ({ currentContent }) => ({ resultDocument: currentContent.split(from).join(to) });
}
