// Orchestrator (the main entry point most callers want)
export { AegisEngine } from './orchestrator/aegisEngine.js';
export type { AegisEditRequest, AegisResult, AegisEngineDeps, ReferenceDocument } from './orchestrator/aegisEngine.js';

// Evidence
export { buildEditProof, serializeEditProof, PROOF_VERSION } from './evidence/editProof.js';
export type { EditProof, RegionEvidence, InvariantEvidence, VerificationResultEvidence } from './evidence/editProof.js';
export { canonicalStringify, stableHash } from './evidence/serialize.js';
export { redact } from './evidence/redact.js';

// Execution / adapters
export type { SuperDocClient, SuperDocSession, SuperDocReceipt, ProposedEdit, OpenDocumentInput } from './execution/superDocClient.js';
export { MockSuperDocClient } from './execution/mockSuperDocClient.js';
export type { MockEditResolver, MockEditInput, MockEditOutcome, MockSuperDocClientOptions } from './execution/mockSuperDocClient.js';
export { fixedResult, sequence, textReplace } from './execution/scenarioResolvers.js';
export { SuperDocError, SuperDocTimeoutError, SuperDocUnavailableError } from './execution/errors.js';

// Intent
export { compileIntent } from './intent/intentCompiler.js';
export { extractScope } from './intent/scopeExtractor.js';
export { extractInvariants } from './intent/invariantExtractor.js';
export { NullAiProvider } from './intent/aiProvider.js';
export type { AiProvider, SemanticComparisonQuestion, SemanticComparisonAnswer } from './intent/aiProvider.js';

// Verification
export { runVerificationSuite } from './verification/index.js';
export type { VerificationRunResult } from './verification/index.js';
export { parsePseudoMarkdown, alignBlocks, findBlock } from './verification/normalize.js';
export type { BlockAlignment } from './verification/normalize.js';
export { registerDriftDetector, listDriftDetectors } from './verification/driftVerifier.js';
export type { DriftDetector } from './verification/driftVerifier.js';

// Risk / decision
export { loadPolicy } from './risk/severityPolicy.js';
export type { VerificationPolicy, PolicyOverride, RejectedOverride } from './risk/severityPolicy.js';
export { classifyFindings, assessRisk, decide } from './risk/decisionEngine.js';

// Recovery
export { runWithRecovery } from './recovery/recoveryController.js';
export type { RecoveryOutcome, RecoveryStepRecord, RecoveryConfig } from './recovery/recoveryController.js';
export { isRecoverable, buildConstrainedInstruction } from './recovery/retryStrategy.js';

// Types
export type { AegisDocument, Block, HeadingBlock, ParagraphBlock, ListBlock, TableBlock, LinkSpan } from './types/document.js';
export { blockPlainText, nthOfKind, ordinalOfKind } from './types/document.js';
export type { CompiledIntent, ScopeSpec, EditKind, RequestedValueChange } from './types/instruction.js';
export type { Severity, Decision, Finding, ClassifiedFinding, CheckerName, CheckerOutcome, RiskAssessment } from './types/verification.js';
export { severityRank, maxSeverity, SEVERITY_ORDER } from './types/verification.js';

// Config / logging
export { loadConfig } from './config/config.js';
export type { AegisConfig } from './config/config.js';
export { Logger } from './logging/logger.js';
export type { LogLevel, LogEvent } from './logging/logger.js';
