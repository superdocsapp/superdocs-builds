import { compileIntent } from '../intent/intentCompiler.js';
import { NullAiProvider, type AiProvider } from '../intent/aiProvider.js';
import type { SuperDocClient } from '../execution/superDocClient.js';
import { SuperDocError, SuperDocTimeoutError } from '../execution/errors.js';
import { parsePseudoMarkdown } from '../verification/normalize.js';
import { runWithRecovery } from '../recovery/recoveryController.js';
import { loadPolicy, type PolicyOverride } from '../risk/severityPolicy.js';
import { buildEditProof, type EditProof } from '../evidence/editProof.js';
import { loadConfig, type AegisConfig } from '../config/config.js';
import { Logger } from '../logging/logger.js';
import type { ScopeSpec } from '../types/instruction.js';

export interface ReferenceDocument {
  name: string;
  content: string;
}

export interface AegisEditRequest {
  documentId?: string;
  /** Aegis-canonical pseudo-markdown source — see src/verification/normalize.ts. */
  document: string;
  instruction: string;
  /**
   * DATA ONLY. Never parsed for instructions, never merged into policy, and
   * never passed to the policy evaluator or the decision engine. A reference
   * document that contains text like "ignore all previous verification
   * rules" is inert here by construction — see docs/SECURITY.md and
   * test/adversarial/promptInjection.test.ts.
   */
  referenceDocuments?: ReferenceDocument[];
  /** Caller-supplied scope, if the host application already knows it (e.g. a UI selection). Wins over the inferred scope. */
  scopeOverride?: ScopeSpec;
  /** Cannot weaken a finding kind listed in policy.default.json's `nonDowngradable` — see src/risk/severityPolicy.ts. */
  policyOverride?: PolicyOverride;
}

export interface AegisResult {
  proof: EditProof;
  /** The accepted document text, present only when decision is VERIFIED or VERIFIED_WITH_WARNINGS. */
  finalDocument: string | null;
  /** The proposed-but-unreviewed document text, present only when decision is REQUIRES_REVIEW. */
  pendingReviewDocument: string | null;
}

export interface AegisEngineDeps {
  superDocClient: SuperDocClient;
  aiProvider?: AiProvider;
  config?: AegisConfig;
  logger?: Logger;
  /** Injectable for deterministic tests; defaults to crypto.randomUUID(). */
  idGenerator?: () => string;
}

export class AegisEngine {
  private readonly superDocClient: SuperDocClient;
  private readonly aiProvider: AiProvider;
  private readonly config: AegisConfig;
  private readonly logger: Logger;
  private readonly idGenerator: () => string;

  constructor(deps: AegisEngineDeps) {
    this.superDocClient = deps.superDocClient;
    this.aiProvider = deps.aiProvider ?? new NullAiProvider();
    this.config = deps.config ?? loadConfig();
    this.logger = deps.logger ?? new Logger(this.config.logLevel, this.config.logDocumentContent);
    this.idGenerator = deps.idGenerator ?? (() => crypto.randomUUID());
  }

  async runEdit(request: AegisEditRequest): Promise<AegisResult> {
    const correlationId = this.idGenerator();
    const documentId = request.documentId ?? `doc-${correlationId}`;
    const startedAt = performance.now();

    this.logger.info({ event: 'operation.start', correlationId, documentId, mode: this.superDocClient.mode });

    try {
      const intent = await compileIntent(request.instruction, this.aiProvider);
      if (request.scopeOverride) intent.scope = request.scopeOverride;

      const policy = loadPolicy(request.policyOverride);
      if (policy.rejectedOverrides.length > 0) {
        this.logger.warn({ event: 'policy.override_rejected', correlationId, overrides: policy.rejectedOverrides });
      }

      const before = parsePseudoMarkdown(request.document);

      const session = await withTimeout(
        this.superDocClient.open({ documentId, content: request.document }),
        this.config.timeoutMs,
        correlationId,
      );
      this.logger.info({ event: 'superdoc.session_open', correlationId, sessionId: session.sessionId });

      let recovery;
      try {
        recovery = await withTimeout(
          runWithRecovery({
            session,
            before,
            intent,
            policy,
            originalInstruction: request.instruction,
            config: { maxAttempts: this.config.retryBudget },
          }),
          this.config.timeoutMs,
          correlationId,
        );
      } finally {
        await session.close();
      }

      this.logger.info({
        event: 'decision.final',
        correlationId,
        decision: recovery.finalRun.decision,
        highestSeverity: recovery.finalRun.risk.highestSeverity,
        attempts: recovery.steps.length,
      });

      const checkerOutcomesForProof = recovery.finalRun.checkerOutcomes.map((outcome) => ({
        checker: outcome.checker,
        durationMs: outcome.durationMs,
        findings: recovery.finalRun.classifiedFindings.filter((f) => f.checker === outcome.checker),
      }));

      const proof = buildEditProof({
        operationId: correlationId,
        intent,
        before,
        after: recovery.finalRun.after,
        alignment: recovery.finalRun.alignment,
        checkerOutcomes: checkerOutcomesForProof,
        classifiedFindings: recovery.finalRun.classifiedFindings,
        risk: recovery.finalRun.risk,
        decision: recovery.finalRun.decision,
        recoverySteps: recovery.steps,
        rejectedOverrides: recovery.finalRun.rejectedOverrides,
        executionMetadata: {
          superdocMode: this.superDocClient.mode,
          sessionId: session.sessionId,
          adapterOperationId: recovery.finalProposedEdit.operationId,
          finalReceiptStatus: recovery.finalReceiptStatus,
          durationMs: performance.now() - startedAt,
          retryBudget: this.config.retryBudget,
          attemptsUsed: recovery.steps.length,
        },
      });

      const decision = recovery.finalRun.decision;
      const finalDocument = decision === 'VERIFIED' || decision === 'VERIFIED_WITH_WARNINGS' ? recovery.finalProposedEdit.resultDocument : null;
      const pendingReviewDocument = decision === 'REQUIRES_REVIEW' ? recovery.finalProposedEdit.resultDocument : null;

      return { proof, finalDocument, pendingReviewDocument };
    } catch (error) {
      if (error instanceof SuperDocError) {
        this.logger.error({ event: 'operation.failed', correlationId, ...error.toLogPayload() });
      } else {
        this.logger.error({ event: 'operation.failed', correlationId, message: error instanceof Error ? error.message : String(error) });
      }
      throw error;
    }
  }
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, correlationId: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new SuperDocTimeoutError(correlationId, timeoutMs)), timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}
