import { basename, extname, resolve } from 'node:path';

import type { ApprovalDecision, SuperDocsClient } from '../api/client.js';
import { SdxError } from '../api/errors.js';
import type { ExportFormat } from '../api/schemas.js';
import { normalizePendingChanges, type ProposedChange } from '../core/changes.js';
import { timing } from '../core/envelope.js';
import { EXIT_CODES, type ExitCode } from '../core/exit-codes.js';
import { pollUntilAction } from '../core/job-state.js';
import type { OutputEnvelope } from '../core/output.js';
import type { OperationLedger } from '../operations/ledger.js';
import type { PendingJobStore } from '../sessions/store.js';
import { defaultEditOutput, exportSession, outputChanges } from './workflow.js';

export interface ApproveOptions {
  readonly jobId: string; readonly accept: readonly string[]; readonly reject: readonly string[];
  readonly acceptAll: boolean; readonly feedback?: string; readonly exportFormat?: ExportFormat;
  readonly outputPath?: string; readonly overwrite: boolean; readonly pollIntervalMs: number;
  readonly timeoutMs: number; readonly signal?: AbortSignal;
}

export interface ApproveDependencies {
  readonly client: SuperDocsClient; readonly jobs: PendingJobStore; readonly ledger: OperationLedger;
  readonly diagnostic: (message: string) => void; readonly now?: () => Date;
}

export interface ApproveResult { readonly exitCode: ExitCode; readonly envelope: OutputEnvelope; }

function duplicates(values: readonly string[]): string[] {
  const seen = new Set<string>(); const duplicate = new Set<string>();
  for (const value of values) { if (seen.has(value)) duplicate.add(value); seen.add(value); }
  return [...duplicate];
}

function createEnvelope(
  status: OutputEnvelope['status'], ok: boolean, options: ApproveOptions,
  sessionId: string, sessionName: string | null, documentName: string,
  documentPath: string | null, documentId: string | null, outputPath: string | null,
  changes: readonly ProposedChange[], decisions: ReadonlyMap<string, boolean>,
  client: SuperDocsClient, startedAt: Date, finishedAt: Date, warnings: readonly string[] = [],
): OutputEnvelope {
  return {
    schemaVersion: '1.0', command: 'approve', status, ok,
    session: { id: sessionId, name: sessionName }, job: { id: options.jobId, name: null },
    document: { id: documentId, name: documentName, format: documentPath ? extname(documentPath).slice(1).toLowerCase() || null : null, path: documentPath, outputPath },
    changes: outputChanges(changes, decisions), usage: client.usage,
    timing: timing(startedAt, finishedAt), warnings: [...warnings], error: null,
  };
}

export async function approveJob(options: ApproveOptions, dependencies: ApproveDependencies): Promise<ApproveResult> {
  const now = dependencies.now ?? (() => new Date()); const startedAt = now();
  if (options.acceptAll && (options.accept.length > 0 || options.reject.length > 0)) {
    throw new SdxError('`--accept-all` cannot be combined with `--accept` or `--reject`.', EXIT_CODES.invalidInput);
  }
  const duplicate = duplicates([...options.accept, ...options.reject]);
  if (duplicate.length > 0) throw new SdxError(`Duplicate decision IDs: ${duplicate.join(', ')}`, EXIT_CODES.invalidInput);
  const conflicts = options.accept.filter((id) => options.reject.includes(id));
  if (conflicts.length > 0) throw new SdxError(`Decision IDs cannot be both accepted and rejected: ${conflicts.join(', ')}`, EXIT_CODES.invalidInput);

  const stored = await dependencies.jobs.get(options.jobId);
  const operation = await dependencies.ledger.byJob(options.jobId);
  const current = await dependencies.client.getJob(options.jobId, options.signal);
  if (current.status !== 'awaiting_approval') {
    throw new SdxError(`Job ${options.jobId} is ${current.status}; approval is only valid while awaiting change review.`, EXIT_CODES.invalidInput);
  }
  if (current.metadata?.awaiting_kind === 'continue_prompt') {
    throw new SdxError(`Job ${options.jobId} is waiting for a continuation decision, not change approval.`, EXIT_CODES.invalidInput);
  }
  if (current.metadata?.pending_changes === undefined) throw new SdxError('The approval job has no pending changes.', EXIT_CODES.schemaMismatch);
  const changes = normalizePendingChanges(current.metadata.pending_changes);
  const pendingIds = new Set(changes.map((change) => change.id));
  const supplied = options.acceptAll ? [...pendingIds] : [...options.accept, ...options.reject];
  const unknown = supplied.filter((id) => !pendingIds.has(id));
  if (unknown.length > 0) throw new SdxError(`Unknown change IDs: ${unknown.join(', ')}`, EXIT_CODES.invalidInput);
  const missing = [...pendingIds].filter((id) => !supplied.includes(id));
  if (missing.length > 0) throw new SdxError(`Every pending change needs a decision. Missing: ${missing.join(', ')}`, EXIT_CODES.invalidInput);
  if (supplied.length === 0) throw new SdxError('No approval decisions were supplied.', EXIT_CODES.invalidInput);

  const accepted = new Set(options.acceptAll ? [...pendingIds] : options.accept);
  const decisions = new Map<string, boolean>();
  const batch: ApprovalDecision[] = changes.map((change) => {
    const approved = accepted.has(change.id); decisions.set(change.id, approved);
    return { change_id: change.id, approved, ...(!approved && options.feedback ? { feedback: options.feedback } : {}) };
  });
  if (operation) await dependencies.ledger.transition(operation.operationId, 'approval-decided', {}, now());
  await dependencies.client.submitApprovalDecisions(current.session_id, options.jobId, batch, options.signal);
  const action = await pollUntilAction(dependencies.client, options.jobId, {
    intervalMs: options.pollIntervalMs, timeoutMs: options.timeoutMs, signal: options.signal,
    onProgress: (job) => dependencies.diagnostic(`Job ${job.status} (${job.progress}%)`),
  });
  if (action.kind !== 'completed') {
    const nextChanges = action.kind === 'approval' ? action.changes : changes;
    if (stored) await dependencies.jobs.put({ ...stored, changes: [...nextChanges], updatedAt: now().toISOString() });
    if (operation) await dependencies.ledger.transition(operation.operationId, action.kind === 'continuation' ? 'waiting-continuation' : 'waiting-approval', {}, now());
    return { exitCode: EXIT_CODES.awaitingApproval, envelope: createEnvelope('awaiting_approval', false, options, current.session_id, stored?.sessionName ?? null, stored?.documentName ?? 'document', stored?.documentPath ?? null, stored?.documentId ?? null, null, nextChanges, decisions, dependencies.client, startedAt, now(), action.kind === 'continuation' ? [action.prompt.message] : []) };
  }
  if ([...decisions.values()].every((value) => !value)) {
    if (operation) await dependencies.ledger.transition(operation.operationId, 'terminal', {}, now());
    await dependencies.jobs.remove(options.jobId);
    return { exitCode: EXIT_CODES.rejected, envelope: createEnvelope('rejected', false, options, current.session_id, stored?.sessionName ?? null, stored?.documentName ?? 'document', stored?.documentPath ?? null, stored?.documentId ?? null, null, changes, decisions, dependencies.client, startedAt, now()) };
  }

  if (operation) await dependencies.ledger.transition(operation.operationId, 'completed', {}, now());
  const format = options.exportFormat ?? stored?.exportFormat ?? undefined;
  let finalOutput: string | null = null; const warnings: string[] = [];
  if (format) {
    if (operation) await dependencies.ledger.transition(operation.operationId, 'export-requested', {}, now());
    const fallback = stored?.documentPath ? defaultEditOutput(stored.documentPath, format) : resolve(`${basename(stored?.documentName ?? 'document', extname(stored?.documentName ?? 'document'))}.sdx.${format === 'markdown' ? 'md' : format}`);
    const destination = options.outputPath ?? stored?.outputPath ?? fallback;
    const exported = await exportSession(dependencies.client, current.session_id, format, destination, stored?.documentPath ?? null, options.overwrite, dependencies.diagnostic, options.signal);
    finalOutput = exported.outputPath; warnings.push(...exported.warnings);
    if (operation) await dependencies.ledger.transition(operation.operationId, 'download-completed', { outputPath: exported.outputPath }, now());
  }
  if (!format && operation) await dependencies.ledger.transition(operation.operationId, 'terminal', {}, now());
  await dependencies.jobs.remove(options.jobId);
  return { exitCode: EXIT_CODES.success, envelope: createEnvelope('completed', true, options, current.session_id, stored?.sessionName ?? null, stored?.documentName ?? 'document', stored?.documentPath ?? null, stored?.documentId ?? null, finalOutput, changes, decisions, dependencies.client, startedAt, now(), warnings) };
}
