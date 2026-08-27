import { resolve } from 'node:path';

import type { ApprovalDecision, SuperDocsClient } from '../api/client.js';
import { SdxError, schemaMismatch } from '../api/errors.js';
import type { ApiJob } from '../api/schemas.js';
import type { ProposedChange } from '../core/changes.js';
import { timing } from '../core/envelope.js';
import { EXIT_CODES, type ExitCode } from '../core/exit-codes.js';
import { pollUntilAction } from '../core/job-state.js';
import type { OutputEnvelope } from '../core/output.js';
import type { OperationLedger } from '../operations/ledger.js';
import type { PendingJob, PendingJobStore } from '../sessions/store.js';
import { withSessionLock } from '../storage/lock.js';
import { exportSession, outputChanges } from './workflow.js';

export interface ResumeOptions {
  readonly jobId?: string; readonly sessionName?: string; readonly approve: boolean;
  readonly overwrite: boolean; readonly pollIntervalMs: number; readonly timeoutMs: number;
  readonly signal?: AbortSignal;
}

export interface ResumeDependencies {
  readonly client: SuperDocsClient; readonly jobs: PendingJobStore; readonly ledger: OperationLedger;
  readonly decideChange: (change: ProposedChange, index: number, total: number) => Promise<{ readonly approved: boolean; readonly feedback?: string }>;
  readonly decideContinuation: (message: string) => Promise<boolean>;
  readonly diagnostic: (message: string) => void; readonly now?: () => Date;
}

export interface ResumeResult { readonly exitCode: ExitCode; readonly envelope: OutputEnvelope; }

function applied(job: ApiJob): boolean {
  return Boolean((job.result?.document_changes?.changes?.length ?? 0) > 0 || (job.result?.document_changes?.chunk_diffs?.length ?? 0) > 0);
}

function envelope(
  status: OutputEnvelope['status'], ok: boolean, pending: PendingJob,
  changes: readonly ProposedChange[], decisions: ReadonlyMap<string, boolean>,
  outputPath: string | null, warnings: readonly string[], client: SuperDocsClient,
  startedAt: Date, finishedAt: Date,
): OutputEnvelope {
  return {
    schemaVersion: '1.0', command: 'resume', status, ok,
    session: { id: pending.sessionId, name: pending.sessionName }, job: { id: pending.jobId, name: null },
    document: {
      id: pending.documentId, name: pending.documentName, format: pending.documentFormat,
      path: pending.documentPath, outputPath,
    },
    changes: outputChanges(changes, decisions), usage: client.usage,
    timing: timing(startedAt, finishedAt), warnings: [...warnings], error: null,
  };
}

async function selectPending(options: ResumeOptions, store: PendingJobStore): Promise<PendingJob> {
  if (options.jobId) {
    const exact = await store.get(options.jobId);
    if (!exact) throw new SdxError(`No persisted resumable state exists for job ${options.jobId}; it was not resubmitted.`, EXIT_CODES.invalidInput);
    return exact;
  }
  const candidates = (await store.list()).filter((job) => options.sessionName === undefined || job.sessionName === options.sessionName);
  if (candidates.length === 0) throw new SdxError(options.sessionName ? `No resumable job exists for session ${options.sessionName}.` : 'No resumable jobs exist.', EXIT_CODES.invalidInput);
  if (candidates.length > 1) throw new SdxError(`Multiple resumable jobs match: ${candidates.map((job) => job.jobId).join(', ')}. Supply an explicit job ID.`, EXIT_CODES.invalidInput);
  return candidates[0] as PendingJob;
}

async function resumeSelected(options: ResumeOptions, dependencies: ResumeDependencies, pending: PendingJob): Promise<ResumeResult> {
  const now = dependencies.now ?? (() => new Date()); const startedAt = now();
  const operation = await dependencies.ledger.byJob(pending.jobId);
  const changes = new Map(pending.changes.map((change) => [change.id, change]));
  const decisions = new Map<string, boolean>(); let submitted = 0; let approved = 0;
  let explicitDecisionPersisted = operation !== undefined && ['approval-decided', 'continuation-decided', 'completed', 'export-requested'].includes(operation.state);
  try {
    while (true) {
      const action = await pollUntilAction(dependencies.client, pending.jobId, {
        intervalMs: options.pollIntervalMs, timeoutMs: options.timeoutMs, signal: options.signal,
        onProgress: (job) => dependencies.diagnostic(`Job ${job.status} (${job.progress}%)`),
      });
      if (action.kind === 'approval') {
        for (const change of action.changes) changes.set(change.id, change);
        await dependencies.jobs.put({ ...pending, changes: [...changes.values()], updatedAt: now().toISOString() });
        if (operation) await dependencies.ledger.transition(operation.operationId, 'waiting-approval', {}, now());
        if (!options.approve) return { exitCode: EXIT_CODES.awaitingApproval, envelope: envelope('awaiting_approval', false, pending, [...changes.values()], decisions, null, [], dependencies.client, startedAt, now()) };
        const batch: ApprovalDecision[] = [];
        for (const [index, change] of action.changes.entries()) {
          const decision = await dependencies.decideChange(change, index + 1, action.changes.length);
          decisions.set(change.id, decision.approved); submitted += 1; if (decision.approved) approved += 1;
          batch.push({ change_id: change.id, approved: decision.approved, ...(decision.feedback ? { feedback: decision.feedback } : {}) });
        }
        if (operation) await dependencies.ledger.transition(operation.operationId, 'approval-decided', {}, now());
        explicitDecisionPersisted = true;
        await dependencies.client.submitApprovalDecisions(pending.sessionId, pending.jobId, batch, options.signal);
        continue;
      }
      if (action.kind === 'continuation') {
        if (operation) await dependencies.ledger.transition(operation.operationId, 'waiting-continuation', {}, now());
        if (!options.approve) return { exitCode: EXIT_CODES.awaitingApproval, envelope: envelope('awaiting_approval', false, pending, [...changes.values()], decisions, null, [action.prompt.message], dependencies.client, startedAt, now()) };
        const shouldContinue = await dependencies.decideContinuation(action.prompt.message);
        if (operation) await dependencies.ledger.transition(operation.operationId, 'continuation-decided', {}, now());
        explicitDecisionPersisted = true;
        await dependencies.client.continueLargeEdit(pending.sessionId, pending.jobId, shouldContinue, options.signal);
        continue;
      }
      if (submitted > 0 && approved === 0) {
        if (operation) await dependencies.ledger.transition(operation.operationId, 'terminal', {}, now());
        await dependencies.jobs.remove(pending.jobId);
        return { exitCode: EXIT_CODES.rejected, envelope: envelope('rejected', false, pending, [...changes.values()], decisions, null, [], dependencies.client, startedAt, now()) };
      }
      if (!applied(action.job) && submitted === 0) {
        if (operation) await dependencies.ledger.transition(operation.operationId, 'terminal', {}, now());
        await dependencies.jobs.remove(pending.jobId);
        return { exitCode: EXIT_CODES.unchanged, envelope: envelope('unchanged', true, pending, [...changes.values()], decisions, null, [], dependencies.client, startedAt, now()) };
      }
      if (applied(action.job) && !explicitDecisionPersisted) {
        throw schemaMismatch('completed review-mode job', new Error('Applied changes have no persisted explicit approval decision.'));
      }
      if (operation) await dependencies.ledger.transition(operation.operationId, 'completed', {}, now());
      let outputPath: string | null = null; const warnings: string[] = [];
      if (pending.exportFormat && pending.outputPath) {
        if (operation) await dependencies.ledger.transition(operation.operationId, 'export-requested', {}, now());
        const exported = await exportSession(dependencies.client, pending.sessionId, pending.exportFormat, resolve(pending.outputPath), pending.documentPath, options.overwrite, dependencies.diagnostic, options.signal);
        outputPath = exported.outputPath; warnings.push(...exported.warnings);
        if (operation) await dependencies.ledger.transition(operation.operationId, 'download-completed', { outputPath }, now());
      } else if (operation) await dependencies.ledger.transition(operation.operationId, 'terminal', {}, now());
      await dependencies.jobs.remove(pending.jobId);
      return { exitCode: EXIT_CODES.success, envelope: envelope('completed', true, pending, [...changes.values()], decisions, outputPath, warnings, dependencies.client, startedAt, now()) };
    }
  } catch (error) {
    if (error instanceof SdxError && error.metadata?.httpStatus === 404) {
      throw new SdxError(`Job ${pending.jobId} is no longer retained by SuperDocs. The edit was not resubmitted; start a new explicit edit if appropriate.`, EXIT_CODES.apiFailure, error.metadata, { cause: error });
    }
    throw error;
  }
}

export async function resumeJob(options: ResumeOptions, dependencies: ResumeDependencies): Promise<ResumeResult> {
  const pending = await selectPending(options, dependencies.jobs);
  const run = () => resumeSelected(options, dependencies, pending);
  return pending.sessionName ? withSessionLock(pending.sessionName, run, { ...(options.signal ? { signal: options.signal } : {}) }) : run();
}
