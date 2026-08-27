import { randomUUID } from 'node:crypto';
import { stat } from 'node:fs/promises';
import { basename, extname, resolve } from 'node:path';

import type { ApprovalDecision, SuperDocsClient } from '../api/client.js';
import { SdxError, asSdxError, schemaMismatch } from '../api/errors.js';
import { verifyExportFile } from '../api/export-validation.js';
import type { ApiJob, ExportFormat } from '../api/schemas.js';
import type { OutputEnvelope } from '../core/output.js';
import { EXIT_CODES, type ExitCode } from '../core/exit-codes.js';
import { pollUntilAction } from '../core/job-state.js';
import type { ProposedChange } from '../core/changes.js';

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

export interface EditOptions {
  readonly documentPath: string;
  readonly instruction: string;
  readonly approve: boolean;
  readonly outputPath: string | undefined;
  readonly format: ExportFormat;
  readonly pollIntervalMs: number;
  readonly timeoutMs: number;
  readonly signal: AbortSignal | undefined;
}

export interface EditDependencies {
  readonly client: SuperDocsClient;
  readonly decideChange: (change: ProposedChange) => Promise<boolean>;
  readonly decideContinuation: (message: string) => Promise<boolean>;
  readonly diagnostic: (message: string) => void;
  readonly now?: () => Date;
}

export interface EditResult {
  readonly exitCode: ExitCode;
  readonly envelope: OutputEnvelope;
}

function mediaTypeFor(path: string): string {
  switch (extname(path).toLowerCase()) {
    case '.docx':
      return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    case '.pdf':
      return 'application/pdf';
    case '.html':
    case '.htm':
      return 'text/html';
    case '.md':
      return 'text/markdown';
    case '.rtf':
      return 'application/rtf';
    case '.txt':
      return 'text/plain';
    default:
      throw new SdxError(
        'Unsupported document type. Use DOCX, PDF, HTML, MD, RTF, or TXT.',
        EXIT_CODES.invalidInput,
      );
  }
}

function outputExtension(format: ExportFormat): string {
  return format === 'markdown' ? 'md' : format;
}

export function defaultOutputPath(
  documentPath: string,
  format: ExportFormat,
): string {
  const inputExtension = extname(documentPath);
  const stem = basename(documentPath, inputExtension);
  return resolve(documentPath, '..', `${stem}.sdx.${outputExtension(format)}`);
}

function toOutputChanges(
  changes: readonly ProposedChange[],
  decisions: ReadonlyMap<string, boolean>,
): OutputEnvelope['changes'] {
  return changes.map((change) => ({
    id: change.id,
    operation: change.operation,
    chunkId: change.chunkId,
    explanation: change.explanation,
    section: change.chunkId,
    summary: change.explanation ?? `${change.operation} change`,
    before: change.oldContent,
    after: change.newContent,
    decision: decisions.has(change.id)
      ? decisions.get(change.id)
        ? 'approved'
        : 'rejected'
      : 'pending',
  }));
}

function didServerApplyChanges(job: ApiJob): boolean {
  const changes = job.result?.document_changes;
  return Boolean(
    (changes?.changes?.length ?? 0) > 0 ||
      (changes?.chunk_diffs?.length ?? 0) > 0,
  );
}

function makeEnvelope(
  status: OutputEnvelope['status'],
  ok: boolean,
  sessionId: string,
  jobId: string,
  documentPath: string,
  outputPath: string | null,
  changes: readonly ProposedChange[],
  decisions: ReadonlyMap<string, boolean>,
  warnings: readonly string[],
  client: SuperDocsClient,
  startedAt: Date,
  finishedAt: Date,
): OutputEnvelope {
  return {
    schemaVersion: '1.0',
    command: 'edit',
    status,
    ok,
    session: { id: sessionId, name: null },
    job: { id: jobId, name: null },
    document: {
      id: null,
      name: basename(documentPath),
      format: extname(documentPath).slice(1).toLowerCase() || null,
      path: documentPath,
      outputPath,
    },
    changes: toOutputChanges(changes, decisions),
    usage: client.usage,
    timing: {
      startedAt: startedAt.toISOString(),
      finishedAt: finishedAt.toISOString(),
      durationMs: Math.max(0, finishedAt.getTime() - startedAt.getTime()),
    },
    warnings: [...warnings],
    error: null,
  };
}

function warningMessages(value: readonly Record<string, unknown>[] | null | undefined): string[] {
  if (value === null || value === undefined) {
    return [];
  }
  return value.map((warning) =>
    typeof warning.message === 'string'
      ? warning.message
      : 'Document parsing completed with a warning.',
  );
}

export async function editDocument(
  options: EditOptions,
  dependencies: EditDependencies,
): Promise<EditResult> {
  const now = dependencies.now ?? (() => new Date());
  const startedAt = now();
  let inputStat;
  try {
    inputStat = await stat(options.documentPath);
  } catch (error) {
    throw asSdxError(
      error,
      `Unable to read input document: ${options.documentPath}`,
      EXIT_CODES.uploadReadFailure,
    );
  }
  if (!inputStat.isFile() || inputStat.size <= 0) {
    throw new SdxError(
      'Input document must be a non-empty regular file.',
      EXIT_CODES.uploadReadFailure,
    );
  }
  if (inputStat.size > MAX_UPLOAD_BYTES) {
    throw new SdxError(
      'Input document exceeds the documented 100 MB pre-signed upload limit.',
      EXIT_CODES.invalidInput,
    );
  }

  const contentType = mediaTypeFor(options.documentPath);
  const filename = basename(options.documentPath);
  const sessionId = `sdx-${randomUUID()}`;
  const desiredOutput =
    options.outputPath === undefined
      ? defaultOutputPath(options.documentPath, options.format)
      : resolve(options.outputPath);
  if (resolve(options.documentPath) === desiredOutput) {
    throw new SdxError(
      'The export path must not overwrite the source document.',
      EXIT_CODES.invalidInput,
    );
  }

  dependencies.diagnostic('Requesting signed upload URL...');
  const upload = await dependencies.client.requestUploadUrl(
    filename,
    contentType,
    inputStat.size,
    options.signal,
  );
  dependencies.diagnostic('Streaming document to signed storage...');
  await dependencies.client.streamUpload(
    upload.upload_url,
    options.documentPath,
    contentType,
    inputStat.size,
    options.signal,
  );
  dependencies.diagnostic('Parsing uploaded document...');
  const parsed = await dependencies.client.processUploadedDocument(
    upload.upload_id,
    sessionId,
    filename,
    options.signal,
  );
  if (
    parsed.session_id !== sessionId ||
    parsed.filename !== filename ||
    parsed.parse_mode !== 'document'
  ) {
    throw schemaMismatch(
      'uploaded-document verification',
      new Error('The parse response did not match the requested document/session.'),
    );
  }

  dependencies.diagnostic('Starting asynchronous edit in review mode...');
  const started = await dependencies.client.startAsyncEdit(
    sessionId,
    options.instruction,
    options.signal,
  );
  if (started.session_id !== sessionId) {
    throw schemaMismatch(
      'async-edit verification',
      new Error('The async response returned a different session.'),
    );
  }

  const changes = new Map<string, ProposedChange>();
  const decisions = new Map<string, boolean>();
  const warnings = warningMessages(parsed.warnings);
  let submittedDecisionCount = 0;
  let approvedDecisionCount = 0;
  let continuationHandled = false;
  let lastProgress = '';

  while (true) {
    const action = await pollUntilAction(dependencies.client, started.job_id, {
      intervalMs: options.pollIntervalMs,
      timeoutMs: options.timeoutMs,
      signal: options.signal,
      onProgress: (job) => {
        const message = `Job ${job.status} (${job.progress}%)`;
        if (message !== lastProgress) {
          dependencies.diagnostic(message);
          lastProgress = message;
        }
      },
    });

    if (action.kind === 'approval') {
      for (const change of action.changes) {
        changes.set(change.id, change);
      }
      if (!options.approve) {
        const finishedAt = now();
        return {
          exitCode: EXIT_CODES.awaitingApproval,
          envelope: makeEnvelope(
            'awaiting_approval',
            false,
            sessionId,
            started.job_id,
            options.documentPath,
            null,
            [...changes.values()],
            decisions,
            warnings,
            dependencies.client,
            startedAt,
            finishedAt,
          ),
        };
      }

      const batch: ApprovalDecision[] = [];
      for (const change of action.changes) {
        const approved = await dependencies.decideChange(change);
        decisions.set(change.id, approved);
        submittedDecisionCount += 1;
        if (approved) {
          approvedDecisionCount += 1;
        }
        batch.push({ change_id: change.id, approved });
      }
      await dependencies.client.submitApprovalDecisions(
        sessionId,
        started.job_id,
        batch,
        options.signal,
      );
      continue;
    }

    if (action.kind === 'continuation') {
      if (!options.approve) {
        warnings.push(action.prompt.message);
        const finishedAt = now();
        return {
          exitCode: EXIT_CODES.awaitingApproval,
          envelope: makeEnvelope(
            'awaiting_approval',
            false,
            sessionId,
            started.job_id,
            options.documentPath,
            null,
            [...changes.values()],
            decisions,
            warnings,
            dependencies.client,
            startedAt,
            finishedAt,
          ),
        };
      }
      const shouldContinue = await dependencies.decideContinuation(
        action.prompt.message,
      );
      continuationHandled = true;
      await dependencies.client.continueLargeEdit(
        sessionId,
        started.job_id,
        shouldContinue,
        options.signal,
      );
      continue;
    }

    if (submittedDecisionCount > 0 && approvedDecisionCount === 0) {
      const finishedAt = now();
      return {
        exitCode: EXIT_CODES.rejected,
        envelope: makeEnvelope(
          'rejected',
          false,
          sessionId,
          started.job_id,
          options.documentPath,
          null,
          [...changes.values()],
          decisions,
          warnings,
          dependencies.client,
          startedAt,
          finishedAt,
        ),
      };
    }

    const changed =
      approvedDecisionCount > 0 ||
      continuationHandled ||
      didServerApplyChanges(action.job);
    if (!changed) {
      const finishedAt = now();
      return {
        exitCode: EXIT_CODES.unchanged,
        envelope: makeEnvelope(
          'unchanged',
          true,
          sessionId,
          started.job_id,
          options.documentPath,
          null,
          [...changes.values()],
          decisions,
          warnings,
          dependencies.client,
          startedAt,
          finishedAt,
        ),
      };
    }
    if (
      approvedDecisionCount === 0 &&
      !continuationHandled &&
      submittedDecisionCount === 0
    ) {
      throw schemaMismatch(
        'completed review-mode job',
        new Error('The server applied changes without an explicit decision.'),
      );
    }

    dependencies.diagnostic('Requesting signed export download URL...');
    const download = await dependencies.client.requestDownloadUrl(
      sessionId,
      options.format,
      basename(desiredOutput, extname(desiredOutput)),
      options.signal,
    );
    dependencies.diagnostic('Streaming and verifying exported document...');
    const downloaded = await dependencies.client.streamDownloadAtomically(
      download.download_url,
      desiredOutput,
      options.signal,
      false,
      (temporaryPath) => verifyExportFile(temporaryPath, options.format),
    );
    warnings.push(...downloaded.warnings);
    const finishedAt = now();
    return {
      exitCode: EXIT_CODES.success,
      envelope: makeEnvelope(
        'completed',
        true,
        sessionId,
        started.job_id,
        options.documentPath,
        desiredOutput,
        [...changes.values()],
        decisions,
        warnings,
        dependencies.client,
        startedAt,
        finishedAt,
      ),
    };
  }
}
