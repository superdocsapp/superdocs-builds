import type { VerificationContext } from '../types/context.js';
import type { CheckerOutcome, Finding } from '../types/verification.js';

export interface DriftDetector {
  name: string;
  /**
   * `priorFindings` holds everything the structural/protected-value/semantic/
   * scope/formatting checkers already found for this run. Drift detectors
   * are meant to *summarize or contextualize* signal that already exists
   * (see docs/ARCHITECTURE.md "Drift is a rollup, not a seventh judge") —
   * they should not re-derive a verdict another checker already owns.
   */
  detect(ctx: VerificationContext, priorFindings: readonly Finding[]): Finding[];
}

const registry: DriftDetector[] = [];

/** Exposed for tests and for host applications registering additional detectors (see class docs above). */
export function registerDriftDetector(detector: DriftDetector): void {
  registry.push(detector);
}

export function listDriftDetectors(): readonly DriftDetector[] {
  return registry;
}

export function runDriftVerifier(ctx: VerificationContext, priorFindings: readonly Finding[]): CheckerOutcome {
  const start = performance.now();
  const findings: Finding[] = [];
  for (const detector of registry) {
    findings.push(...detector.detect(ctx, priorFindings));
  }
  return { checker: 'drift', findings, durationMs: performance.now() - start };
}

// ---------------------------------------------------------------------------
// Built-in detectors
// ---------------------------------------------------------------------------

/**
 * Flags an edit that touched far more of the document than its stated scope
 * would suggest, even if no single change tripped the scope verifier (e.g.
 * many small, individually-plausible tweaks scattered across an unscoped
 * "improve this" instruction). This is intentionally coarse and low
 * confidence — it is a smoke detector, not a verdict.
 */
registerDriftDetector({
  name: 'textual-drift',
  detect(ctx) {
    const totalBefore = ctx.before.blocks.length;
    // Percentage-changed is meaningless noise on tiny documents (a
    // one-paragraph document is trivially "100% changed" by any edit at
    // all) — only evaluate once there's enough structure for a ratio to
    // mean something.
    if (totalBefore < 4) return [];

    const changedCount = ctx.alignment.filter((a) => a.kind !== 'unchanged').length;
    const ratio = changedCount / totalBefore;
    const isNarrowScope = ctx.intent.scope.kind === 'paragraph-index' || ctx.intent.scope.kind === 'heading';
    if (isNarrowScope) return []; // scopeVerifier already enforces narrow scopes precisely; don't double-flag.

    const threshold = ctx.intent.editKind === 'style-only' ? 0.7 : 0.85;
    if (ratio <= threshold) return [];

    return [
      {
        id: 'drift:textual:1',
        checker: 'drift',
        kind: 'DRIFT_TEXTUAL_EXCESSIVE',
        confidence: 0.5,
        message: `${Math.round(ratio * 100)}% of the document's blocks changed for a "${ctx.intent.editKind}" edit. That may be legitimate for a big rewrite, but it is unusually broad for the stated intent and is worth a human glance.`,
      },
    ];
  },
});

/**
 * A pure summary of what the protected-value verifier already found — not a
 * second opinion. Gives the EditProof's `drift_results` a single number to
 * show even when there are zero violations, so "0 protected invariant
 * violations" in the demo output is a real count, not a placeholder.
 */
registerDriftDetector({
  name: 'numeric-drift-rollup',
  detect(_ctx, priorFindings) {
    const numericKinds = new Set([
      'PROTECTED_VALUE_CURRENCY_CHANGED',
      'PROTECTED_VALUE_DATE_CHANGED',
      'PROTECTED_VALUE_DURATION_CHANGED',
      'PROTECTED_VALUE_PERCENTAGE_CHANGED',
      'PROTECTED_VALUE_TIME_CHANGED',
      'PROTECTED_VALUE_INTEGER_CHANGED',
      'PROTECTED_VALUE_DECIMAL_CHANGED',
    ]);
    const count = priorFindings.filter((f) => numericKinds.has(f.kind)).length;
    if (count === 0) return [];
    return [
      {
        id: 'drift:numeric-rollup:1',
        checker: 'drift',
        kind: 'DRIFT_NUMERIC_SUMMARY',
        confidence: 1,
        message: `${count} protected numeric/date/currency value(s) changed without being requested (see protected_value findings for detail).`,
      },
    ];
  },
});

// Documented, not implemented, extension points (see docs/ARCHITECTURE.md
// "Future extension points" for what each would need):
//   - unit-drift:            comparing quantities across unit systems
//                            (e.g. "30 days" vs "1 month") requires a unit
//                            conversion table; today these compare as
//                            unrelated protected values, which is safe
//                            (over-flagging) but not unit-aware.
//   - backtranslation-drift: round-tripping text through a translation API
//                            and comparing meaning requires a translation
//                            provider this environment does not have
//                            credentials for.
