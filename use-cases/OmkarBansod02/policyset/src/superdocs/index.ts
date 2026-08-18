/**
 * Server-side SuperDocs adapter. Do not import from Client Components.
 * All calls require SUPERDOCS_API_KEY from the process environment.
 */

export { SuperDocsClient, buildStartChatPayload, createSessionId } from "./client";
export { getSuperDocsApiKey } from "./config";
export {
  PROVIDER_DETAIL_MAX_LENGTH,
  SuperDocsError,
  SuperDocsInvalidResponse,
  SuperDocsRequestError,
  redactSecrets,
  type SuperDocsErrorDiagnostics,
} from "./errors";
export {
  evaluateReturnWindowCoverage,
  type ManagedCoverageProblem,
  type ManagedCoverageResult,
} from "./managed-coverage";
export {
  PolicySetSuperDocsSafetyError,
  PolicySetSynchronizedStartError,
  assertPendingChangesTargetDocument,
  assertSynchronizedProposalCoverage,
  assertSynchronizedProposalGate,
  assertSynchronizedProposalSafety,
  assertTargetedProposalGate,
  buildTargetedSynchronizedInstruction,
  createPolicySetSuperDocsClient,
  exportPolicyDocument,
  getPolicyDocumentEditJob,
  getPolicyTargetedSynchronizedJob,
  getPolicySetSessionDocuments,
  initializePolicySetSession,
  startPolicySynchronizedEdit,
  startPolicyDocumentEdit,
  submitPolicyDocumentReview,
  submitPolicyTargetedSynchronizedReview,
  policyDocumentExportFilename,
  type PolicyDocumentExport,
} from "./policyset";
export {
  runSessionLockExperiment,
  type SessionLockExperimentInput,
  type SessionLockExperimentOutcome,
  type SessionLockExperimentResult,
} from "./session-lock-experiment";
export {
  classifyProposalTarget,
  persistPendingProposalEvidence,
  type ProposalEvidenceOptions,
  type ProposalTargetClassification,
} from "./proposal-evidence";
export {
  DOCX_MIME,
  PDF_MIME,
  SUPERDOCS_API_BASE,
  SUPERDOCS_JOB_STATUSES,
  SUPERDOCS_OPEN_MODES,
  type ExportArtifact,
  type ExportFormat,
  type FocusedDocument,
  type IngestedDocument,
  type JobReference,
  type JobSnapshot,
  type PendingChange,
  type ReviewDecision,
  type ReviewReceipt,
  type SessionDocument,
  type SessionDocumentIdentity,
  type StartChatInput,
  type SuperDocsClientOptions,
  type SuperDocsJobStatus,
  type SuperDocsOpenMode,
} from "./types";
