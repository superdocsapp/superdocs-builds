import { createWriteStream } from 'node:fs';
import { chmod, mkdtemp, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { extname, join, resolve } from 'node:path';
import { pipeline } from 'node:stream/promises';

import type { SuperDocsClient } from '../api/client.js';
import { SdxError } from '../api/errors.js';
import type { ExportFormat } from '../api/schemas.js';
import { timing } from '../core/envelope.js';
import { EXIT_CODES, type ExitCode } from '../core/exit-codes.js';
import type { OutputEnvelope } from '../core/output.js';
import type { PendingJobStore, SessionStore} from '../sessions/store.js';
import { validateAlias } from '../sessions/store.js';
import { exportSession, loadDocument, newServerSessionId, outputExtension, safeTitleSlug, safeUploadTitle, validateSource } from './workflow.js';

export interface NewOptions {
  readonly filePath?: string; readonly title: string; readonly format: ExportFormat;
  readonly outputPath?: string; readonly sessionName?: string; readonly overwrite: boolean;
  readonly signal?: AbortSignal;
}

export interface NewDependencies {
  readonly client: SuperDocsClient; readonly sessions: SessionStore; readonly jobs: PendingJobStore;
  readonly input: NodeJS.ReadableStream; readonly inputIsTTY: boolean;
  readonly diagnostic: (message: string) => void; readonly now?: () => Date;
}

export interface NewResult { readonly exitCode: ExitCode; readonly envelope: OutputEnvelope; }

export async function createDocument(options: NewOptions, dependencies: NewDependencies): Promise<NewResult> {
  const now = dependencies.now ?? (() => new Date()); const startedAt = now();
  const title = options.title.trim(); if (!title) throw new SdxError('`--title` must not be empty.', EXIT_CODES.invalidInput);
  const sessionName = options.sessionName ? validateAlias(options.sessionName) : undefined;
  if (sessionName && await dependencies.sessions.get(sessionName)) throw new SdxError(`Session ${sessionName} already exists; new will not replace it.`, EXIT_CODES.invalidInput);
  let temporaryDirectory: string | undefined; let sourcePath = options.filePath;
  try {
    if (sourcePath === undefined) {
      if (dependencies.inputIsTTY) throw new SdxError('No input file was supplied and stdin is a terminal. Pipe Markdown/text or provide a file.', EXIT_CODES.invalidInput);
      temporaryDirectory = await mkdtemp(join(tmpdir(), 'sdx-new-')); await chmod(temporaryDirectory, 0o700);
      sourcePath = join(temporaryDirectory, 'stdin.md');
      await pipeline(dependencies.input, createWriteStream(sourcePath, { flags: 'wx', mode: 0o600 }), { signal: options.signal });
      if ((await stat(sourcePath)).size === 0) throw new SdxError('stdin was empty.', EXIT_CODES.invalidInput);
    } else if (!['.md', '.txt', '.html', '.htm'].includes(extname(sourcePath).toLowerCase())) {
      throw new SdxError('`sdx new` accepts Markdown, TXT, or HTML source content.', EXIT_CODES.invalidInput);
    }
    const source = await validateSource(sourcePath);
    const sessionId = newServerSessionId(); const extension = extname(source.canonicalPath).toLowerCase() || '.md';
    const uploadName = safeUploadTitle(title, extension === '.htm' ? '.html' : extension);
    const parsed = await loadDocument(dependencies.client, source, sessionId, uploadName, dependencies.diagnostic, options.signal);
    const destination = resolve(options.outputPath ?? `${safeTitleSlug(title)}.${outputExtension(options.format)}`);
    const exported = await exportSession(dependencies.client, sessionId, options.format, destination, options.filePath ? source.canonicalPath : null, options.overwrite, dependencies.diagnostic, options.signal);
    const stamp = now().toISOString();
    if (sessionName) await dependencies.sessions.put({
      name: sessionName, serverSessionId: sessionId,
      durableDocumentId: parsed.durable_document_id ?? null, sessionDocumentId: parsed.document_id ?? null,
      canonicalSourcePath: options.filePath ? source.canonicalPath : `stdin:${title}`,
      sourceSha256: source.sha256, lastJobId: null, lastExportFormat: options.format,
      lastOutputPath: exported.outputPath, createdAt: stamp, updatedAt: stamp,
    });
    return { exitCode: EXIT_CODES.success, envelope: {
      schemaVersion: '1.0', command: 'new', status: 'completed', ok: true,
      session: { id: sessionId, name: sessionName ?? null }, job: null,
      document: { id: parsed.durable_document_id ?? parsed.document_id ?? null, name: title, format: extension.slice(1), path: options.filePath ? source.canonicalPath : null, outputPath: exported.outputPath },
      changes: [], usage: dependencies.client.usage, timing: timing(startedAt, now()), warnings: [...exported.warnings], error: null,
    } };
  } finally {
    if (temporaryDirectory) await rm(temporaryDirectory, { recursive: true, force: true });
  }
}
