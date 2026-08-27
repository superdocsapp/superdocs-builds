import { randomUUID } from 'node:crypto';
import { stat } from 'node:fs/promises';
import { basename, dirname, extname, resolve } from 'node:path';

import type { SuperDocsClient } from '../api/client.js';
import { SdxError, asSdxError, schemaMismatch } from '../api/errors.js';
import { verifyExportFile } from '../api/export-validation.js';
import type { ExportFormat, ProcessDocumentResponse } from '../api/schemas.js';
import type { ProposedChange } from '../core/changes.js';
import { EXIT_CODES } from '../core/exit-codes.js';
import type { OutputEnvelope } from '../core/output.js';
import { sectionFromChange } from '../presentation/diff.js';
import { sha256File } from '../sessions/store.js';

export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

export interface ValidatedSource {
  readonly canonicalPath: string;
  readonly filename: string;
  readonly contentType: string;
  readonly size: number;
  readonly sha256: string;
}

export interface LoadDocumentHooks {
  readonly onUploadPrepared?: (uploadId: string) => Promise<void>;
  readonly onUploadCompleted?: (uploadId: string) => Promise<void>;
  readonly onDocumentProcessed?: (document: ProcessDocumentResponse) => Promise<void>;
}

export function mediaTypeFor(path: string): string {
  switch (extname(path).toLowerCase()) {
    case '.docx': return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    case '.pdf': return 'application/pdf';
    case '.html': case '.htm': return 'text/html';
    case '.md': return 'text/markdown';
    case '.rtf': return 'application/rtf';
    case '.txt': return 'text/plain';
    default: throw new SdxError('Unsupported document type. Use DOCX, PDF, HTML, MD, RTF, or TXT.', EXIT_CODES.invalidInput);
  }
}

export async function validateSource(path: string): Promise<ValidatedSource> {
  const canonicalPath = resolve(path);
  let information;
  try { information = await stat(canonicalPath); }
  catch (error) { throw asSdxError(error, `Unable to read input document: ${canonicalPath}`, EXIT_CODES.uploadReadFailure); }
  if (!information.isFile() || information.size <= 0) {
    throw new SdxError('Input document must be a non-empty regular file.', EXIT_CODES.uploadReadFailure);
  }
  if (information.size > MAX_UPLOAD_BYTES) {
    throw new SdxError('Input document exceeds the documented 100 MB upload limit.', EXIT_CODES.invalidInput);
  }
  return {
    canonicalPath, filename: basename(canonicalPath), contentType: mediaTypeFor(canonicalPath),
    size: information.size, sha256: await sha256File(canonicalPath),
  };
}

export function outputExtension(format: ExportFormat): string { return format === 'markdown' ? 'md' : format; }

export function defaultEditOutput(path: string, format: ExportFormat): string {
  const extension = extname(path);
  return resolve(dirname(path), `${basename(path, extension)}.sdx.${outputExtension(format)}`);
}

export function safeTitleSlug(title: string): string {
  const slug = title.normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase().slice(0, 120);
  if (!slug || slug === '.' || slug === '..') throw new SdxError('Title does not contain usable filename characters.', EXIT_CODES.invalidInput);
  return slug;
}

export function safeUploadTitle(title: string, extension: string): string {
  const cleaned = title.replace(/[\u0000-\u001f<>:"/\\|?*]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 180);
  if (!cleaned || cleaned === '.' || cleaned === '..') throw new SdxError('Title is not valid.', EXIT_CODES.invalidInput);
  return `${cleaned}${extension}`;
}

export async function loadDocument(
  client: SuperDocsClient, source: ValidatedSource, sessionId: string,
  uploadFilename: string, diagnostic: (message: string) => void, signal?: AbortSignal,
  hooks: LoadDocumentHooks = {},
): Promise<ProcessDocumentResponse> {
  diagnostic('Requesting signed upload URL...');
  const upload = await client.requestUploadUrl(uploadFilename, source.contentType, source.size, signal);
  await hooks.onUploadPrepared?.(upload.upload_id);
  diagnostic('Streaming document to signed storage...');
  await client.streamUpload(upload.upload_url, source.canonicalPath, source.contentType, source.size, signal);
  await hooks.onUploadCompleted?.(upload.upload_id);
  diagnostic('Parsing uploaded document...');
  const parsed = await client.processUploadedDocument(upload.upload_id, sessionId, uploadFilename, signal);
  if (parsed.session_id !== sessionId || parsed.filename !== uploadFilename || parsed.parse_mode !== 'document') {
    throw schemaMismatch('uploaded-document verification', new Error('The parse response did not match the requested document/session.'));
  }
  await hooks.onDocumentProcessed?.(parsed);
  return parsed;
}

export async function exportSession(
  client: SuperDocsClient, sessionId: string, format: ExportFormat, destination: string,
  sourcePath: string | null, overwrite: boolean, diagnostic: (message: string) => void,
  signal?: AbortSignal,
): Promise<{ readonly outputPath: string; readonly warnings: readonly string[] }> {
  const outputPath = resolve(destination);
  if (sourcePath !== null && resolve(sourcePath) === outputPath) {
    throw new SdxError('The export path must not overwrite the source document.', EXIT_CODES.invalidInput);
  }
  diagnostic('Requesting signed export download URL...');
  const download = await client.requestDownloadUrl(sessionId, format, basename(outputPath, extname(outputPath)), signal);
  diagnostic('Streaming and verifying exported document...');
  const result = await client.streamDownloadAtomically(
    download.download_url,
    outputPath,
    signal,
    overwrite,
    (temporaryPath) => verifyExportFile(temporaryPath, format),
  );
  return { outputPath, warnings: result.warnings };
}

export function outputChanges(changes: readonly ProposedChange[], decisions: ReadonlyMap<string, boolean> = new Map()): OutputEnvelope['changes'] {
  return changes.map((change) => ({
    id: change.id, operation: change.operation, chunkId: change.chunkId,
    explanation: change.explanation, documentId: change.documentId,
    section: sectionFromChange(change), summary: change.explanation ?? `${change.operation} change`,
    before: change.oldContent, after: change.newContent,
    decision: decisions.has(change.id) ? (decisions.get(change.id) ? 'approved' : 'rejected') : 'pending',
  }));
}

export function newServerSessionId(): string { return `sdx-${randomUUID()}`; }
