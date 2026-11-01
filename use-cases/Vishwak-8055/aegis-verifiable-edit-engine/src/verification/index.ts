import type { AegisDocument } from '../types/document.js';
import type { CompiledIntent } from '../types/instruction.js';
import type { CheckerOutcome, ClassifiedFinding, Decision, RiskAssessment } from '../types/verification.js';
import type { VerificationPolicy, RejectedOverride } from '../risk/severityPolicy.js';
import { classifyFindings, assessRisk, decide } from '../risk/decisionEngine.js';
import { parsePseudoMarkdown, alignBlocks, type BlockAlignment } from './normalize.js';
import { runStructuralVerifier } from './structuralVerifier.js';
import { runProtectedValueVerifier } from './protectedValueVerifier.js';
import { runSemanticVerifier } from './semanticVerifier.js';
import { runScopeVerifier } from './scopeVerifier.js';
import { runFormattingVerifier } from './formattingVerifier.js';
import { runDriftVerifier } from './driftVerifier.js';

export interface VerificationRunResult {
  after: AegisDocument;
  alignment: BlockAlignment[];
  checkerOutcomes: CheckerOutcome[];
  classifiedFindings: ClassifiedFinding[];
  risk: RiskAssessment;
  decision: Decision;
  rejectedOverrides: RejectedOverride[];
}

/**
 * Runs all six verification layers (structural, protected-value, semantic,
 * scope, formatting, drift) and the risk/decision engine, given the ORIGINAL
 * `before` document (already parsed once, reused across retries — see
 * docs/ARCHITECTURE.md "Performance") and the raw proposed `afterRaw` text.
 */
export function runVerificationSuite(
  before: AegisDocument,
  afterRaw: string,
  intent: CompiledIntent,
  policy: VerificationPolicy,
): VerificationRunResult {
  const after = parsePseudoMarkdown(afterRaw);
  const alignment = alignBlocks(before.blocks, after.blocks);
  const ctx = { before, after, alignment, intent };

  const structural = runStructuralVerifier(ctx);
  const protectedValue = runProtectedValueVerifier(ctx);
  const semantic = runSemanticVerifier(ctx);
  const scope = runScopeVerifier(ctx);
  const formatting = runFormattingVerifier(ctx);
  const priorFindings = [
    ...structural.findings,
    ...protectedValue.findings,
    ...semantic.findings,
    ...scope.findings,
    ...formatting.findings,
  ];
  const drift = runDriftVerifier(ctx, priorFindings);

  const checkerOutcomes: CheckerOutcome[] = [structural, protectedValue, semantic, scope, formatting, drift];
  const allFindings = checkerOutcomes.flatMap((outcome) => outcome.findings);
  const classifiedFindings = classifyFindings(allFindings, policy);
  const risk = assessRisk(classifiedFindings);
  const decision = decide(risk, policy);

  return { after, alignment, checkerOutcomes, classifiedFindings, risk, decision, rejectedOverrides: policy.rejectedOverrides };
}

export { parsePseudoMarkdown, alignBlocks };
