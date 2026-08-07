import { basename, extname, resolve } from 'node:path';

import type { ApprovalDecision, SuperDocsClient } from '../api/client.js';
import { SdxError, schemaMismatch } from '../api/errors.js';
import type { ApiJob, ExportFormat } from '../api/schemas.js';
import type { ModelTier } from '../config/store.js';
import type { ProposedChange } from '../core/changes.js';
import { timing } from '../core/envelope.js';
import { EXIT_CODES, type ExitCode } from '../core/exit-codes.js';
import { pollUntilAction } from '../core/job-state.js';
import type { OutputEnvelope } from '../core/output.js';
import type { OperationLedger } from '../operations/ledger.js';
import type { PendingJob, SessionRecord , PendingJobStore, SessionStore} from '../sessions/store.js';
import { validateAlias } from '../sessions/store.js';
import { defaultEditOutput, exportSession, loadDocument, newServerSessionId, outputChanges, validateSource } from './workflow.js';

export interface InteractiveDecision { readonly approved: boolean; readonly feedback?: string; }

export interface EditV3Options {
  readonly documentPath: string; readonly instruction: string; readonly approve: boolean;
  readonly outputPath?: string; readonly format: ExportFormat; readonly modelTier: ModelTier;
  readonly sessionName?: string; readonly pollIntervalMs: number; readonly timeoutMs: number;
  readonly overwrite: boolean; readonly signal?: AbortSignal;
}

export interface EditV3Dependencies {
  readonly client: SuperDocsClient; readonly sessions: SessionStore; readonly jobs: PendingJobStore; readonly ledger: OperationLedger;
  readonly decideChange: (change: ProposedChange, index: number, total: number) => Promise<InteractiveDecision>;
  readonly decideContinuation: (message: string) => Promise<boolean>;
  readonly diagnostic: (message: string) => void; readonly onJobStarted?: (jobId: string) => void; readonly now?: () => Date;
}

export interface EditV3Result { readonly exitCode: ExitCode; readonly envelope: OutputEnvelope; }

function serverApplied(job: ApiJob): boolean {
  const changes = job.result?.document_changes;
  return Boolean((changes?.changes?.length ?? 0) > 0 || (changes?.chunk_diffs?.length ?? 0) > 0);
}

function warningsFrom(value: readonly Record<string, unknown>[] | null | undefined): string[] {
  return value?.map((warning) => typeof warning.message === 'string' ? warning.message : 'Document parsing completed with a warning.') ?? [];
}

function envelope(
  status: OutputEnvelope['status'], ok: boolean, sessionId: string, sessionName: string | undefined,
  jobId: string, sourcePath: string, documentId: string | null, outputPath: string | null,
  changes: readonly ProposedChange[], decisions: ReadonlyMap<string, boolean>, warnings: readonly string[],
  client: SuperDocsClient, startedAt: Date, finishedAt: Date,
): OutputEnvelope {
  return {
    schemaVersion: '1.0', command: 'edit', status, ok,
    session: { id: sessionId, name: sessionName ?? null }, job: { id: jobId, name: null },
    document: { id: documentId, name: basename(sourcePath), format: extname(sourcePath).slice(1).toLowerCase() || null, path: sourcePath, outputPath },
    changes: outputChanges(changes, decisions), usage: client.usage, timing: timing(startedAt, finishedAt),
    warnings: [...warnings], error: null,
  };
}

function pendingRecord(
  jobId: string, sessionId: string, sessionName: string | undefined, sourcePath: string,
  documentId: string | null, destination: string, format: ExportFormat,
  changes: readonly ProposedChange[], createdAt: string, updatedAt: string,
): PendingJob {
  return {
    jobId, sessionId, sessionName: sessionName ?? null, documentPath: sourcePath,
    documentName: basename(sourcePath), documentFormat: extname(sourcePath).slice(1).toLowerCase() || null,
    documentId, outputPath: destination, exportFormat: format, changes: [...changes], createdAt, updatedAt,
  };
}

export async function editDocumentV3(options: EditV3Options, dependencies: EditV3Dependencies): Promise<EditV3Result> {
  const now = dependencies.now ?? (() => new Date());
  const startedAt = now();
  const source = await validateSource(options.documentPath);
  const sessionName = options.sessionName ? validateAlias(options.sessionName) : undefined;
  const destination = resolve(options.outputPath ?? defaultEditOutput(source.canonicalPath, options.format));
  let stored: SessionRecord | undefined = sessionName ? await dependencies.sessions.get(sessionName) : undefined;
  if (stored && stored.canonicalSourcePath !== source.canonicalPath) {
    throw new SdxError(`Session ${sessionName} belongs to ${stored.canonicalSourcePath}; choose another alias.`, EXIT_CODES.invalidInput);
  }
  if (stored && stored.sourceSha256 !== source.sha256) {
    throw new SdxError(`Local source changed since session ${sessionName} was uploaded. No remote document was replaced; use a new alias.`, EXIT_CODES.invalidInput);
  }

  const sessionId = stored?.serverSessionId ?? newServerSessionId();
  const operation = await dependencies.ledger.prepare({
    instruction: options.instruction, sourceSha256: source.sha256, sessionId,
    sourcePath: source.canonicalPath, sourceFilename: source.filename,
    sourceContentType: source.contentType, sourceSize: source.size,
    sessionName: sessionName ?? null, exportFormat: options.format, outputPath: destination, now: startedAt,
  });
  let documentId = stored?.sessionDocumentId ?? stored?.durableDocumentId ?? null;
  const warnings: string[] = [];
  if (!stored) {
    const parsed = await loadDocument(dependencies.client, source, sessionId, source.filename, dependencies.diagnostic, options.signal, {
      onUploadPrepared: async (uploadId) => { await dependencies.ledger.transition(operation.operationId, 'upload-prepared', { uploadId }, now()); },
      onUploadCompleted: async (uploadId) => { await dependencies.ledger.transition(operation.operationId, 'upload-completed', { uploadId }, now()); },
      onDocumentProcessed: async (document) => {
        await dependencies.ledger.transition(operation.operationId, 'document-processed', {
          documentId: document.document_id ?? document.durable_document_id ?? null,
        }, now());
      },
    });
    documentId = parsed.document_id ?? parsed.durable_document_id ?? null;
    warnings.push(...warningsFrom(parsed.warnings));
    if (sessionName) {
      const stamp = now().toISOString();
      stored = {
        name: sessionName, serverSessionId: sessionId,
        durableDocumentId: parsed.durable_document_id ?? null, sessionDocumentId: parsed.document_id ?? null,
        canonicalSourcePath: source.canonicalPath, sourceSha256: source.sha256,
        lastJobId: null, lastExportFormat: null, lastOutputPath: null, createdAt: stamp, updatedAt: stamp,
      };
      await dependencies.sessions.put(stored);
    }
  } else {
    dependencies.diagnostic(`Reusing named session ${sessionName}; no upload performed.`);
  }

  dependencies.diagnostic('Starting asynchronous edit in review mode...');
  await dependencies.ledger.transition(operation.operationId, 'submission-started', {}, now());
  let started: Awaited<ReturnType<SuperDocsClient['startAsyncEdit']>>;
  try {
    started = await dependencies.client.startAsyncEdit(sessionId, options.instruction, options.signal, {
      modelTier: options.modelTier, ...(documentId ? { documentId } : {}),
    });
  } catch (error) {
    if (error instanceof SdxError && error.metadata?.remoteState === 'unknown') {
      await dependencies.ledger.transition(operation.operationId, 'unknown', {}, now());
      throw new SdxError(
        `${error.message} Operation ${operation.operationId} is recorded for manual reconciliation; do not repeat the edit.`,
        error.exitCode, { ...error.metadata, operationId: operation.operationId }, { cause: error },
      );
    }
    await dependencies.ledger.transition(operation.operationId, 'failed', {}, now());
    throw error;
  }
  if (started.session_id !== sessionId) throw schemaMismatch('async-edit verification', new Error('The async response returned a different session.'));
  await dependencies.ledger.transition(operation.operationId, 'acknowledged', { jobId: started.job_id }, now());
  dependencies.onJobStarted?.(started.job_id);
  const createdStamp = now().toISOString();
  await dependencies.jobs.put(pendingRecord(started.job_id, sessionId, sessionName, source.canonicalPath, documentId, destination, options.format, [], createdStamp, createdStamp));
  if (stored) await dependencies.sessions.put({ ...stored, lastJobId: started.job_id, lastExportFormat: options.format, lastOutputPath: destination, updatedAt: createdStamp });

  const changes = new Map<string, ProposedChange>();
  const decisions = new Map<string, boolean>();
  let submitted = 0; let approved = 0; let continuationHandled = false; let lastProgress = '';
  while (true) {
    const action = await pollUntilAction(dependencies.client, started.job_id, {
      intervalMs: options.pollIntervalMs, timeoutMs: options.timeoutMs, signal: options.signal,
      onProgress: (job) => { const message = `Job ${job.status} (${job.progress}%)`; if (message !== lastProgress) { dependencies.diagnostic(message); lastProgress = message; } },
    });
    if (action.kind === 'approval') {
      for (const change of action.changes) changes.set(change.id, change);
      await dependencies.jobs.put(pendingRecord(started.job_id, sessionId, sessionName, source.canonicalPath, documentId, destination, options.format, [...changes.values()], createdStamp, now().toISOString()));
      await dependencies.ledger.transition(operation.operationId, 'waiting-approval', {}, now());
      if (!options.approve) {
        const finished = now();
        return { exitCode: EXIT_CODES.awaitingApproval, envelope: envelope('awaiting_approval', false, sessionId, sessionName, started.job_id, source.canonicalPath, documentId, null, [...changes.values()], decisions, warnings, dependencies.client, startedAt, finished) };
      }
      const batch: ApprovalDecision[] = [];
      for (const [index, change] of action.changes.entries()) {
        const decision = await dependencies.decideChange(change, index + 1, action.changes.length);
        decisions.set(change.id, decision.approved); submitted += 1; if (decision.approved) approved += 1;
        batch.push({ change_id: change.id, approved: decision.approved, ...(decision.feedback ? { feedback: decision.feedback } : {}) });
      }
      await dependencies.ledger.transition(operation.operationId, 'approval-decided', {}, now());
      await dependencies.client.submitApprovalDecisions(sessionId, started.job_id, batch, options.signal);
      continue;
    }
    if (action.kind === 'continuation') {
      await dependencies.ledger.transition(operation.operationId, 'waiting-continuation', {}, now());
      if (!options.approve) {
        warnings.push(action.prompt.message);
        return { exitCode: EXIT_CODES.awaitingApproval, envelope: envelope('awaiting_approval', false, sessionId, sessionName, started.job_id, source.canonicalPath, documentId, null, [...changes.values()], decisions, warnings, dependencies.client, startedAt, now()) };
      }
      const shouldContinue = await dependencies.decideContinuation(action.prompt.message);
      continuationHandled = true;
      await dependencies.ledger.transition(operation.operationId, 'continuation-decided', {}, now());
      await dependencies.client.continueLargeEdit(sessionId, started.job_id, shouldContinue, options.signal);
      continue;
    }
    if (submitted > 0 && approved === 0) {
      await dependencies.ledger.transition(operation.operationId, 'terminal', {}, now());
      await dependencies.jobs.remove(started.job_id);
      return { exitCode: EXIT_CODES.rejected, envelope: envelope('rejected', false, sessionId, sessionName, started.job_id, source.canonicalPath, documentId, null, [...changes.values()], decisions, warnings, dependencies.client, startedAt, now()) };
    }
    const changed = approved > 0 || continuationHandled || serverApplied(action.job);
    if (!changed) {
      await dependencies.ledger.transition(operation.operationId, 'terminal', {}, now());
      await dependencies.jobs.remove(started.job_id);
      return { exitCode: EXIT_CODES.unchanged, envelope: envelope('unchanged', true, sessionId, sessionName, started.job_id, source.canonicalPath, documentId, null, [...changes.values()], decisions, warnings, dependencies.client, startedAt, now()) };
    }
    if (approved === 0 && !continuationHandled && submitted === 0) throw schemaMismatch('completed review-mode job', new Error('The server applied changes without an explicit decision.'));
    await dependencies.ledger.transition(operation.operationId, 'completed', {}, now());
    await dependencies.ledger.transition(operation.operationId, 'export-requested', {}, now());
    const exported = await exportSession(dependencies.client, sessionId, options.format, destination, source.canonicalPath, options.overwrite, dependencies.diagnostic, options.signal);
    warnings.push(...exported.warnings); await dependencies.jobs.remove(started.job_id);
    await dependencies.ledger.transition(operation.operationId, 'download-completed', { outputPath: exported.outputPath }, now());
    return { exitCode: EXIT_CODES.success, envelope: envelope('completed', true, sessionId, sessionName, started.job_id, source.canonicalPath, documentId, exported.outputPath, [...changes.values()], decisions, warnings, dependencies.client, startedAt, now()) };
  }
}
