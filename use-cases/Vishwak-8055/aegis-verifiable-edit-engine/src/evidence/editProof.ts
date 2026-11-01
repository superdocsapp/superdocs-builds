import type { CompiledIntent, ScopeSpec } from '../types/instruction.js';
import type { ClassifiedFinding, Decision, Severity } from '../types/verification.js';
import type { BlockAlignment } from '../verification/normalize.js';
import type { AegisDocument } from '../types/document.js';
import type { RecoveryStepRecord } from '../recovery/recoveryController.js';
import type { RejectedOverride } from '../risk/severityPolicy.js';
import { blockPlainText } from '../types/document.js';
import { canonicalStringify, stableHash } from './serialize.js';
import { redact } from './redact.js';

export const PROOF_VERSION = '1.0.0';
const EXCERPT_LIMIT = 220;

export interface RegionEvidence {
  kind: 'unchanged' | 'modified' | 'inserted' | 'deleted';
  before_block_id?: string;
  after_block_id?: string;
  before_excerpt?: string;
  after_excerpt?: string;
}

export interface InvariantEvidence {
  key: string;
  label: string;
  passed: boolean;
  violating_finding_ids: string[];
}

export interface VerificationResultEvidence {
  checker: string;
  passed: boolean;
  finding_count: number;
  duration_ms: number;
}

export interface EditProof {
  proof_version: string;
  operation_id: string;
  timestamp: string;
  intent: {
    instruction_text: string;
    summary: string;
    edit_kind: string;
    scope: ScopeSpec;
    confidence: number;
    ai_assisted: boolean;
  };
  scope: ScopeSpec;
  changed_regions: RegionEvidence[];
  unchanged_regions: RegionEvidence[];
  protected_invariants: InvariantEvidence[];
  verification_results: VerificationResultEvidence[];
  drift_results: { kind: string; message: string }[];
  risk_assessment: {
    highest_severity: Severity;
    counts: Record<Severity, number>;
  };
  decision: Decision;
  evidence: {
    proof_hash: string;
    findings: ClassifiedFinding[];
    attempts: RecoveryStepRecord[];
    rejected_policy_overrides: RejectedOverride[];
  };
  execution_metadata: {
    superdoc_mode: 'mock' | 'live';
    session_id: string;
    adapter_operation_id: string;
    final_receipt_status: 'applied' | 'rejected' | 'pending';
    duration_ms: number;
    checker_durations_ms: Record<string, number>;
    retry_budget: number;
    attempts_used: number;
  };
}

const INVARIANT_GROUPS: { key: string; label: string; kinds: string[] }[] = [
  { key: 'numbers_preserved', label: 'Numbers preserved', kinds: ['PROTECTED_VALUE_INTEGER_CHANGED', 'PROTECTED_VALUE_DECIMAL_CHANGED', 'PROTECTED_VALUE_PERCENTAGE_CHANGED'] },
  { key: 'dates_preserved', label: 'Dates & durations preserved', kinds: ['PROTECTED_VALUE_DATE_CHANGED', 'PROTECTED_VALUE_DURATION_CHANGED', 'PROTECTED_VALUE_TIME_CHANGED'] },
  { key: 'currency_preserved', label: 'Currency preserved', kinds: ['PROTECTED_VALUE_CURRENCY_CHANGED'] },
  { key: 'links_preserved', label: 'Links & identifiers preserved', kinds: ['STRUCTURAL_LINK_REMOVED', 'STRUCTURAL_LINK_URL_CHANGED', 'PROTECTED_VALUE_URL_CHANGED', 'PROTECTED_VALUE_IDENTIFIER_CHANGED'] },
  { key: 'obligations_preserved', label: 'Obligations & permissions preserved', kinds: ['SEMANTIC_OBLIGATION_TO_PERMISSION', 'SEMANTIC_MODALITY_INVERTED', 'SEMANTIC_MODALITY_TIGHTENED', 'SEMANTIC_MODALITY_CHANGED', 'SEMANTIC_ACTOR_CHANGED', 'SEMANTIC_CONDITION_OR_EXCEPTION_REMOVED'] },
  { key: 'structure_preserved', label: 'Structure preserved', kinds: ['STRUCTURAL_BLOCK_INSERTED', 'STRUCTURAL_BLOCK_DELETED', 'STRUCTURAL_TYPE_CHANGED', 'STRUCTURAL_HEADING_LEVEL_CHANGED', 'STRUCTURAL_TABLE_DIMENSION_CHANGED'] },
  { key: 'scope_respected', label: 'Scope respected', kinds: ['UNINTENDED_SCOPE_CHANGE', 'SCOPE_TARGET_NOT_FOUND'] },
  { key: 'formatting_clean', label: 'Formatting clean', kinds: ['FORMATTING_MARKER_UNBALANCED'] },
];

export interface BuildEditProofInput {
  operationId: string;
  intent: CompiledIntent;
  before: AegisDocument;
  after: AegisDocument;
  alignment: BlockAlignment[];
  checkerOutcomes: { checker: string; findings: ClassifiedFinding[]; durationMs: number }[];
  classifiedFindings: ClassifiedFinding[];
  risk: { highestSeverity: Severity; counts: Record<Severity, number> };
  decision: Decision;
  recoverySteps: RecoveryStepRecord[];
  rejectedOverrides: RejectedOverride[];
  executionMetadata: {
    superdocMode: 'mock' | 'live';
    sessionId: string;
    adapterOperationId: string;
    finalReceiptStatus: 'applied' | 'rejected' | 'pending';
    durationMs: number;
    retryBudget: number;
    attemptsUsed: number;
  };
}

export function buildEditProof(input: BuildEditProofInput): EditProof {
  const changed_regions: RegionEvidence[] = [];
  const unchanged_regions: RegionEvidence[] = [];

  for (const entry of input.alignment) {
    const region: RegionEvidence = {
      kind: entry.kind,
      before_block_id: 'beforeId' in entry ? entry.beforeId : undefined,
      after_block_id: 'afterId' in entry ? entry.afterId : undefined,
      before_excerpt: 'beforeId' in entry ? excerptFor(input.before, entry.beforeId) : undefined,
      after_excerpt: 'afterId' in entry ? excerptFor(input.after, entry.afterId) : undefined,
    };
    if (entry.kind === 'unchanged') unchanged_regions.push(region);
    else changed_regions.push(region);
  }

  const protected_invariants: InvariantEvidence[] = INVARIANT_GROUPS.map((group) => {
    const violating = input.classifiedFindings.filter(
      (f) => group.kinds.includes(f.kind) && severityAtLeast(f.severity, 'MEDIUM'),
    );
    return { key: group.key, label: group.label, passed: violating.length === 0, violating_finding_ids: violating.map((f) => f.id) };
  });

  const verification_results: VerificationResultEvidence[] = input.checkerOutcomes.map((outcome) => ({
    checker: outcome.checker,
    passed: !outcome.findings.some((f) => severityAtLeast(f.severity, 'MEDIUM')),
    finding_count: outcome.findings.length,
    duration_ms: Math.round(outcome.durationMs * 100) / 100,
  }));

  const drift_results = (input.checkerOutcomes.find((o) => o.checker === 'drift')?.findings ?? []).map((f) => ({
    kind: f.kind,
    message: f.message,
  }));

  const checker_durations_ms: Record<string, number> = {};
  for (const outcome of input.checkerOutcomes) checker_durations_ms[outcome.checker] = Math.round(outcome.durationMs * 100) / 100;

  const proofWithoutHash: EditProof = {
    proof_version: PROOF_VERSION,
    operation_id: input.operationId,
    timestamp: new Date().toISOString(),
    intent: {
      instruction_text: input.intent.instructionText,
      summary: input.intent.summary,
      edit_kind: input.intent.editKind,
      scope: input.intent.scope,
      confidence: input.intent.confidence,
      ai_assisted: input.intent.aiAssisted,
    },
    scope: input.intent.scope,
    changed_regions,
    unchanged_regions,
    protected_invariants,
    verification_results,
    drift_results,
    risk_assessment: { highest_severity: input.risk.highestSeverity, counts: input.risk.counts },
    decision: input.decision,
    evidence: {
      proof_hash: '',
      findings: input.classifiedFindings,
      attempts: input.recoverySteps,
      rejected_policy_overrides: input.rejectedOverrides,
    },
    execution_metadata: redact({
      superdoc_mode: input.executionMetadata.superdocMode,
      session_id: input.executionMetadata.sessionId,
      adapter_operation_id: input.executionMetadata.adapterOperationId,
      final_receipt_status: input.executionMetadata.finalReceiptStatus,
      duration_ms: Math.round(input.executionMetadata.durationMs * 100) / 100,
      checker_durations_ms,
      retry_budget: input.executionMetadata.retryBudget,
      attempts_used: input.executionMetadata.attemptsUsed,
    }),
  };

  const proof_hash = stableHash({ ...proofWithoutHash, evidence: { ...proofWithoutHash.evidence, proof_hash: undefined } });
  return { ...proofWithoutHash, evidence: { ...proofWithoutHash.evidence, proof_hash } };
}

function excerptFor(doc: AegisDocument, blockId: string): string | undefined {
  const block = doc.blocks.find((b) => b.id === blockId);
  if (!block) return undefined;
  const text = blockPlainText(block);
  return text.length > EXCERPT_LIMIT ? `${text.slice(0, EXCERPT_LIMIT)}…` : text;
}

function severityAtLeast(severity: Severity, floor: Severity): boolean {
  const order: Severity[] = ['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];
  return order.indexOf(severity) >= order.indexOf(floor);
}

/** Deterministic, secret-free JSON text for an EditProof — safe to write to disk, log, or display. */
export function serializeEditProof(proof: EditProof): string {
  return canonicalStringify(proof);
}
