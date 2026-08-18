/**
 * ONE-SHOT EXPERIMENT SUPPORT — not part of the product workflow.
 *
 * Answers exactly one question:
 *
 *   Can SuperDocs start a second pinned `/chat/async` job in the same session
 *   while the first job is `awaiting_approval`?
 *
 * The failed targeted run started both jobs back-to-back, so the second start
 * raced the first job's `pending`/`in_progress` phase. This sequences them
 * instead: the first document's job is polled to `awaiting_approval` and
 * gated, and only then is the second start attempted.
 *
 * This module NEVER approves anything. It leaves the first job awaiting a
 * decision so the caller can deny it explicitly. Nothing here is retried,
 * cancelled, or compensated. `startPolicySynchronizedEdit` is untouched, so
 * the production workflow is unchanged.
 */
import type { PolicyDocumentType, ChangeSet } from "@/domain";
import type { SuperDocsJobView } from "@/app/policyset/superdocs-contract";

import type { SuperDocsClient } from "./client";
import {
  SuperDocsRequestError,
  type SuperDocsErrorDiagnostics,
} from "./errors";
import {
  PolicySetSuperDocsSafetyError,
  buildTargetedSynchronizedInstruction,
  createPolicySetSuperDocsClient,
  getPolicyTargetedSynchronizedJob,
} from "./policyset";
import type { ProposalEvidenceOptions } from "./proposal-evidence";

/**
 * Structurally identical to the adapter surface `getPolicyTargetedSynchronizedJob`
 * requires. `uploadDocx` is unused here but kept so the two stay assignable.
 */
type ExperimentClient = Pick<
  SuperDocsClient,
  "uploadDocx" | "startChat" | "getJob" | "submitReview" | "listSessionDocuments"
>;

export type SessionLockExperimentOutcome =
  /** The first job's own gate failed; the second start was never attempted. */
  | "first_gate_failed"
  /** Second start rejected while the first job was awaiting_approval. */
  | "second_start_rejected"
  /** Both pinned jobs coexisted in one session. */
  | "second_start_accepted";

export type SessionLockExperimentResult = {
  outcome: SessionLockExperimentOutcome;
  firstDocumentType: PolicyDocumentType;
  secondDocumentType: PolicyDocumentType;
  /** Chat starts SuperDocs accepted, counted as each one returns. */
  locallyObservedSuccessfulChatStarts: number;
  firstJob: SuperDocsJobView | null;
  /** Status of the first job at the moment the second start was attempted. */
  firstJobStatusAtSecondStart: string | null;
  secondJob: SuperDocsJobView | null;
  /** Structured provider diagnostics for a rejected second start. */
  secondStartError: SuperDocsErrorDiagnostics | null;
  secondStartMessage: string | null;
  firstGateError: string | null;
};

export type SessionLockExperimentInput = {
  sessionId: string;
  documentIds: Record<PolicyDocumentType, string>;
  changeSet: ChangeSet;
  firstDocumentType: PolicyDocumentType;
  secondDocumentType: PolicyDocumentType;
  /** Polls the first job until it settles into a reviewable state. */
  awaitFirstJobReview: (
    poll: () => Promise<SuperDocsJobView>,
  ) => Promise<SuperDocsJobView>;
};

/**
 * Costs at most two paid chat starts. Callers must treat a non-null
 * `firstJob` as an outstanding batch that still needs an explicit denial.
 */
export async function runSessionLockExperiment(
  input: SessionLockExperimentInput,
  client: ExperimentClient = createPolicySetSuperDocsClient(),
  evidenceOptions: ProposalEvidenceOptions = {},
): Promise<SessionLockExperimentResult> {
  const result: SessionLockExperimentResult = {
    outcome: "first_gate_failed",
    firstDocumentType: input.firstDocumentType,
    secondDocumentType: input.secondDocumentType,
    locallyObservedSuccessfulChatStarts: 0,
    firstJob: null,
    firstJobStatusAtSecondStart: null,
    secondJob: null,
    secondStartError: null,
    secondStartMessage: null,
    firstGateError: null,
  };

  const firstReference = await client.startChat({
    sessionId: input.sessionId,
    documentId: input.documentIds[input.firstDocumentType],
    message: buildTargetedSynchronizedInstruction(
      input.changeSet,
      input.firstDocumentType,
    ),
  });
  result.locallyObservedSuccessfulChatStarts += 1;
  if (firstReference.sessionId !== input.sessionId) {
    throw new PolicySetSuperDocsSafetyError(
      "SuperDocs returned a synchronized edit job for a different session.",
    );
  }
  result.firstJob = {
    jobId: firstReference.jobId,
    sessionId: firstReference.sessionId,
    status: firstReference.status,
    progress: null,
    proposals: [],
    errorCode: null,
  };

  // Poll to awaiting_approval. The gate (targeting safety + managed-occurrence
  // coverage) runs inside getPolicyTargetedSynchronizedJob, which also denies
  // this job's own batch if the gate fails.
  try {
    result.firstJob = await input.awaitFirstJobReview(() =>
      getPolicyTargetedSynchronizedJob(
        {
          jobId: firstReference.jobId,
          sessionId: input.sessionId,
          documentType: input.firstDocumentType,
          documentIds: input.documentIds,
          changeSet: input.changeSet,
        },
        client,
        evidenceOptions,
      ),
    );
  } catch (error) {
    result.outcome = "first_gate_failed";
    result.firstGateError = error instanceof Error ? error.message : String(error);
    return result;
  }

  if (
    result.firstJob.status !== "awaiting_approval" ||
    result.firstJob.proposals.length === 0
  ) {
    result.outcome = "first_gate_failed";
    result.firstGateError = `The ${input.firstDocumentType} job reached ${result.firstJob.status} without a reviewable batch; the second start was not attempted.`;
    return result;
  }

  // The first job is deliberately left awaiting_approval — NOT approved.
  result.firstJobStatusAtSecondStart = result.firstJob.status;

  try {
    const secondReference = await client.startChat({
      sessionId: input.sessionId,
      documentId: input.documentIds[input.secondDocumentType],
      message: buildTargetedSynchronizedInstruction(
        input.changeSet,
        input.secondDocumentType,
      ),
    });
    result.locallyObservedSuccessfulChatStarts += 1;
    result.outcome = "second_start_accepted";
    result.secondJob = {
      jobId: secondReference.jobId,
      sessionId: secondReference.sessionId,
      status: secondReference.status,
      progress: null,
      proposals: [],
      errorCode: null,
    };
  } catch (error) {
    result.outcome = "second_start_rejected";
    result.secondStartMessage =
      error instanceof Error ? error.message : String(error);
    result.secondStartError =
      error instanceof SuperDocsRequestError ? error.diagnostics() : null;
  }

  return result;
}
