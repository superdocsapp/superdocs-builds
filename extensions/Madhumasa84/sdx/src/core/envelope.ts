import { basename, extname } from 'node:path';

import type { SdxError } from '../api/errors.js';
import { redactText, redactUnknown } from '../security/redaction.js';
import type { OutputEnvelope } from './output.js';

export function timing(startedAt: Date, finishedAt = new Date()): OutputEnvelope['timing'] {
  return {
    startedAt: startedAt.toISOString(),
    finishedAt: finishedAt.toISOString(),
    durationMs: Math.max(0, finishedAt.getTime() - startedAt.getTime()),
  };
}

export function baseEnvelope(command: string, startedAt: Date, overrides: Partial<OutputEnvelope> = {}): OutputEnvelope {
  return {
    schemaVersion: '1.0', command, status: 'completed', ok: true,
    session: null, job: null, document: null, changes: [], usage: null,
    timing: timing(startedAt), warnings: [], error: null, ...overrides,
  };
}

export function failureEnvelope(command: string, error: SdxError, startedAt: Date, documentPath?: string): OutputEnvelope {
  return baseEnvelope(command, startedAt, {
    status: 'failed', ok: false,
    document: documentPath ? {
      id: null, name: basename(documentPath),
      format: extname(documentPath).slice(1).toLowerCase() || null,
      path: documentPath, outputPath: null,
    } : null,
    error: { code: `SDX_${error.exitCode}`, message: redactText(error.message), details: redactUnknown(error.metadata) },
  });
}
