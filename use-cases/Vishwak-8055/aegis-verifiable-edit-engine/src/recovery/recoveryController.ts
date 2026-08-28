import type { SuperDocSession, ProposedEdit } from '../execution/superDocClient.js';
import type { AegisDocument } from '../types/document.js';
import type { CompiledIntent } from '../types/instruction.js';
import type { Decision, Severity } from '../types/verification.js';
import type { VerificationPolicy } from '../risk/severityPolicy.js';
import { runVerificationSuite, type VerificationRunResult } from '../verification/index.js';
import { isRecoverable, buildConstrainedInstruction } from './retryStrategy.js';

export interface RecoveryConfig {
  /** Number of RETRIES allowed after the first attempt. Total proposeEdit calls is at most 1 + maxAttempts. */
  maxAttempts: number;
}

export interface RecoveryStepRecord {
  attempt: number;
  instructionUsed: string;
  decision: Decision;
  highestSeverity: Severity;
  findingCount: number;
}

export interface RecoveryOutcome {
  steps: RecoveryStepRecord[];
  finalRun: VerificationRunResult;
  finalInstructionUsed: string;
  finalProposedEdit: ProposedEdit;
  finalReceiptStatus: 'applied' | 'rejected' | 'pending';
}

/**
 * Runs the propose→verify loop, retrying with a tightened instruction when
 * (and only when) the failure is policy-marked recoverable, bounded by
 * `config.maxAttempts`. The full six-checker suite re-runs on every single
 * attempt (brief section 13.5) — there is no partial/fast-path re-check.
 *
 * The tracked change is committed (`accept`) only on VERIFIED /
 * VERIFIED_WITH_WARNINGS, explicitly rejected on BLOCKED, and left pending
 * on REQUIRES_REVIEW — Aegis never auto-accepts a result a human hasn't
 * seen, and never auto-rejects one that might just need a human's sign-off.
 */
export async function runWithRecovery(input: {
  session: SuperDocSession;
  before: AegisDocument;
  intent: CompiledIntent;
  policy: VerificationPolicy;
  originalInstruction: string;
  config: RecoveryConfig;
}): Promise<RecoveryOutcome> {
  const steps: RecoveryStepRecord[] = [];
  let instruction = input.originalInstruction;
  let attempt = 0;
  let lastProposed: ProposedEdit | undefined;
  let lastRun: VerificationRunResult | undefined;

  for (;;) {
    attempt++;
    const proposed = await input.session.proposeEdit(instruction);
    const run = runVerificationSuite(input.before, proposed.resultDocument, input.intent, input.policy);

    steps.push({
      attempt,
      instructionUsed: instruction,
      decision: run.decision,
      highestSeverity: run.risk.highestSeverity,
      findingCount: run.classifiedFindings.length,
    });
    lastProposed = proposed;
    lastRun = run;

    const isGood = run.decision === 'VERIFIED' || run.decision === 'VERIFIED_WITH_WARNINGS';
    if (isGood) break;

    const canRetry = attempt <= input.config.maxAttempts && isRecoverable(run.classifiedFindings);
    if (!canRetry) break;

    await input.session.decideTrackedChanges('reject');
    instruction = buildConstrainedInstruction(input.originalInstruction, run.classifiedFindings);
  }

  const finalRun = lastRun as VerificationRunResult;
  const finalProposedEdit = lastProposed as ProposedEdit;
  let finalReceiptStatus: 'applied' | 'rejected' | 'pending';

  if (finalRun.decision === 'VERIFIED' || finalRun.decision === 'VERIFIED_WITH_WARNINGS') {
    await input.session.decideTrackedChanges('accept');
    finalReceiptStatus = 'applied';
  } else if (finalRun.decision === 'BLOCKED') {
    await input.session.decideTrackedChanges('reject');
    finalReceiptStatus = 'rejected';
  } else {
    // REQUIRES_REVIEW: intentionally left pending for a human reviewer.
    finalReceiptStatus = 'pending';
  }

  return { steps, finalRun, finalInstructionUsed: instruction, finalProposedEdit, finalReceiptStatus };
}
