import { runDeterministicAudit } from "./deterministicAudit";
import { runVerifier } from "./verifier";
import type { VerifierCaller, VerifierConfig } from "./verifier";
import { BANDS } from "./lexicon";
import { injectionFindings, scanIntakeFields } from "../injection";
import { textFromHtml } from "../textFromHtml";
import type { AuditReport, Intake } from "../types";

export { BANDS, BAND_ORDER, bandRank } from "./lexicon";
export { runDeterministicAudit } from "./deterministicAudit";
export { runVerifier, readVerifierConfig, extractJsonObject } from "./verifier";

const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 } as const;

/**
 * The full calibration audit.
 *
 * Stage order matters. The free deterministic checks run first and always
 * complete, so that a slow or missing verifier can never leave the writer with
 * nothing. The verifier is additive.
 *
 * Nothing here mutates the letter. Every check produces a finding for a human
 * to act on. Auto-correcting an inflated letter would defeat the point: the
 * writer, not the tool, is the one signing it.
 */
export async function runAudit(params: {
  letterHtml: string;
  intake: Intake;
  config?: VerifierConfig | null;
  caller?: VerifierCaller;
}): Promise<AuditReport> {
  const timings: Record<string, number> = {};
  const clock = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

  const t0 = clock();
  const letterText = textFromHtml(params.letterHtml);
  timings.extract_text = Math.round(clock() - t0);

  const t1 = clock();
  const deterministic = runDeterministicAudit({
    text: letterText,
    band: params.intake.strengthBand,
    reservations: params.intake.reservations,
  });
  timings.lexicon = Math.round(clock() - t1);

  const t2 = clock();
  const injectionHits = scanIntakeFields({
    reservations: params.intake.reservations,
    toneNotes: params.intake.toneNotes,
    relationship: params.intake.relationship,
    subjectRole: params.intake.subjectRole,
    ...Object.fromEntries(
      params.intake.evidence.flatMap((item, i) => [
        [`evidence ${i + 1} claim`, item.claim],
        [`evidence ${i + 1} support`, item.evidence],
      ]),
    ),
  });
  const injection = injectionFindings(injectionHits);
  timings.injection_scan = Math.round(clock() - t2);

  const t3 = clock();
  const verifier = await runVerifier({
    letterText,
    evidence: params.intake.evidence,
    declaredBand: params.intake.strengthBand,
    config: params.config,
    caller: params.caller,
  });
  timings.verifier = Math.round(clock() - t3);

  const findings = [...deterministic, ...injection, ...verifier.findings].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  );

  const drift =
    verifier.inferredBand !== undefined
      ? BANDS[verifier.inferredBand].rank - BANDS[params.intake.strengthBand].rank
      : undefined;

  return {
    declaredBand: params.intake.strengthBand,
    inferredBand: verifier.inferredBand,
    drift,
    findings,
    checks: {
      lexicon: "ran",
      reservations: "ran",
      injection: "ran",
      verifier: verifier.status === "ok" ? "ran" : verifier.status,
    },
    verifierNote: verifier.reason,
    timings,
  };
}
