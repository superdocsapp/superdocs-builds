import { createSuperDocsClient, SuperDocsClient } from './superdocs';
import { createGenerationContext, buildSuperDocsInstruction } from './context';
import { computeFileHashesAsync, FileHashMap } from '../utils/hash';
import { planRegeneration, DocumentType } from './revision';
import { parseProposedChangeBatch } from '../utils/parser';
import { ProposedChange, ProposedChangeBatch, ExportResult } from '../types/superdocs';

export type ProgrammaticApprovalGate = (
  changes: ProposedChange[],
  batch: ProposedChangeBatch
) => Promise<{ approved: boolean; selectedChanges: ProposedChange[] }> | { approved: boolean; selectedChanges: ProposedChange[] };

export interface HeadlessGenerationOptions {
  apiKey: string;
  files: Map<string, string>;
  documentType: DocumentType;
  instruction?: string;
  approvalGate?: ProgrammaticApprovalGate;
  exportFormat?: 'pdf' | 'docx';
  signal?: AbortSignal;
  client?: SuperDocsClient;
}

export interface HeadlessRunResult {
  sessionId: string;
  documentId: string;
  jobId: string;
  proposedChanges: ProposedChangeBatch;
  approvedChanges: ProposedChange[];
  rejectedChanges: ProposedChange[];
  baselineHashes: FileHashMap;
  exportResult?: ExportResult;
  exportedBlob?: Blob;
}

export interface HeadlessRevisionOptions {
  apiKey: string;
  sessionId: string;
  documentType: DocumentType;
  originalInstruction: string;
  baselineHashes: FileHashMap;
  currentFiles: Map<string, string>;
  approvalGate?: ProgrammaticApprovalGate;
  exportFormat?: 'pdf' | 'docx';
  signal?: AbortSignal;
  client?: SuperDocsClient;
}

export interface HeadlessRevisionResult {
  hasChanges: boolean;
  sessionId: string;
  jobId?: string;
  proposedChanges?: ProposedChangeBatch;
  approvedChanges?: ProposedChange[];
  baselineHashes: FileHashMap;
  exportResult?: ExportResult;
  exportedBlob?: Blob;
  telemetry?: Record<string, unknown>;
}

/**
 * Headless machine runner for SuperDocs (Behavior #4: Machine-drivable).
 * Runs the complete lifecycle programmatically without UI interaction:
 * Context Ingestion -> Upload -> Chat Async -> Polling -> Programmatic Gate Approval -> Export.
 */
export async function runHeadlessGeneration(
  options: HeadlessGenerationOptions
): Promise<HeadlessRunResult> {
  const {
    apiKey,
    files,
    documentType,
    instruction = '',
    approvalGate,
    exportFormat = 'pdf',
    signal,
    client = createSuperDocsClient(apiKey),
  } = options;

  if (files.size === 0) {
    throw new Error('No files provided for context generation');
  }

  // 1. Ingest context and capture SHA-256 baseline
  const baselineHashes = await computeFileHashesAsync(files);
  const context = createGenerationContext(documentType, instruction, files);
  const formattedPrompt = buildSuperDocsInstruction(context);

  // 2. Base upload to SuperDocs
  const filename = `${documentType.toUpperCase()}.md`;
  const uploadResult = await client.uploadDocument(filename, formattedPrompt, undefined, true, signal);

  // 3. Initiate async chat generation
  const jobId = await client.chatAsync({
    message: formattedPrompt,
    session_id: uploadResult.session_id,
    approval_mode: 'ask_every_time',
    model_tier: 'core',
  }, signal);

  // 4. Poll until job reaches awaiting_approval
  const jobStatus = await client.waitForJob(jobId, undefined, signal);

  if (jobStatus.status === 'failed') {
    throw new Error(jobStatus.error || 'Headless generation job failed');
  }

  let proposedBatch: ProposedChangeBatch = {
    batch_id: 'batch_empty',
    batch_total: 0,
    changes: [],
    awaiting_kind: 'approval',
  };

  let approvedList: ProposedChange[] = [];
  let rejectedList: ProposedChange[] = [];

  if (jobStatus.status === 'awaiting_approval' && jobStatus.metadata?.pending_changes) {
    const rawChanges = typeof jobStatus.metadata.pending_changes === 'string'
      ? jobStatus.metadata.pending_changes
      : JSON.stringify(jobStatus.metadata.pending_changes);
    proposedBatch = parseProposedChangeBatch(rawChanges);

    // 5. Programmatic Gate (Machine Approval Operation)
    const decision = approvalGate
      ? await approvalGate(proposedBatch.changes, proposedBatch)
      : { approved: true, selectedChanges: proposedBatch.changes };

    approvedList = decision.approved ? decision.selectedChanges : [];
    const selectedIds = new Set(approvedList.map(c => c.change_id));
    rejectedList = proposedBatch.changes.filter(c => !selectedIds.has(c.change_id));

    await client.approveChanges({
      session_id: uploadResult.session_id,
      job_id: jobId,
      approved: decision.approved && approvedList.length > 0,
      changes: approvedList,
    }, signal);
  }

  // 6. Export finished document artifact
  let exportResult: ExportResult | undefined;
  let exportedBlob: Blob | undefined;

  if (exportFormat) {
    exportResult = await client.exportDocument({
      session_id: uploadResult.session_id,
      format: exportFormat,
    }, signal);

    exportedBlob = await client.downloadExport(exportResult.download_url, signal);
  }

  return {
    sessionId: uploadResult.session_id,
    documentId: uploadResult.document_id,
    jobId,
    proposedChanges: proposedBatch,
    approvedChanges: approvedList,
    rejectedChanges: rejectedList,
    baselineHashes,
    exportResult,
    exportedBlob,
  };
}

/**
 * Headless machine runner for zero-drift revisions.
 * Diffs current files against baseline and requests only targeted updates.
 */
export async function runHeadlessRevision(
  options: HeadlessRevisionOptions
): Promise<HeadlessRevisionResult> {
  const {
    apiKey,
    sessionId,
    documentType,
    originalInstruction,
    baselineHashes,
    currentFiles,
    approvalGate,
    exportFormat = 'pdf',
    signal,
    client = createSuperDocsClient(apiKey),
  } = options;

  // 1. Compute deterministic hash diff
  const plan = await planRegeneration(
    baselineHashes,
    currentFiles,
    documentType,
    originalInstruction
  );

  // Short-circuit on zero source changes (Zero-drift guarantee)
  if (!plan.hasChanges) {
    return {
      hasChanges: false,
      sessionId,
      baselineHashes,
      telemetry: { savings: '100%', reason: 'No source changes detected' },
    };
  }

  // 2. Submit targeted revision message
  const jobId = await client.chatAsync({
    message: plan.message!,
    session_id: sessionId,
    approval_mode: 'ask_every_time',
    model_tier: 'core',
  }, signal);

  // 3. Poll until awaiting approval
  const jobStatus = await client.waitForJob(jobId, undefined, signal);

  if (jobStatus.status === 'failed') {
    throw new Error(jobStatus.error || 'Headless revision job failed');
  }

  let proposedBatch: ProposedChangeBatch | undefined;
  let approvedList: ProposedChange[] = [];

  if (jobStatus.status === 'awaiting_approval' && jobStatus.metadata?.pending_changes) {
    const rawChanges = typeof jobStatus.metadata.pending_changes === 'string'
      ? jobStatus.metadata.pending_changes
      : JSON.stringify(jobStatus.metadata.pending_changes);
    proposedBatch = parseProposedChangeBatch(rawChanges);

    const decision = approvalGate
      ? await approvalGate(proposedBatch.changes, proposedBatch)
      : { approved: true, selectedChanges: proposedBatch.changes };

    approvedList = decision.approved ? decision.selectedChanges : [];

    await client.approveChanges({
      session_id: sessionId,
      job_id: jobId,
      approved: decision.approved && approvedList.length > 0,
      changes: approvedList,
    }, signal);
  }

  // 4. Update baseline and export
  const newBaseline = await computeFileHashesAsync(currentFiles);
  let exportResult: ExportResult | undefined;
  let exportedBlob: Blob | undefined;

  if (exportFormat) {
    exportResult = await client.exportDocument({
      session_id: sessionId,
      format: exportFormat,
    }, signal);
    exportedBlob = await client.downloadExport(exportResult.download_url, signal);
  }

  return {
    hasChanges: true,
    sessionId,
    jobId,
    proposedChanges: proposedBatch,
    approvedChanges: approvedList,
    baselineHashes: newBaseline,
    exportResult,
    exportedBlob,
    telemetry: plan.diff.telemetry as unknown as Record<string, unknown>,
  };
}
