import { z } from 'zod';

import { PendingChangeSchema, type PendingChange } from '../api/schemas.js';
import { schemaMismatch } from '../api/errors.js';

export interface ProposedChange {
  readonly id: string;
  readonly operation: 'edit' | 'create' | 'delete';
  readonly chunkId: string | null;
  readonly documentId: string | null;
  readonly oldContent: string | null;
  readonly newContent: string | null;
  readonly explanation: string | null;
}

export interface ContinuePrompt {
  readonly message: string;
  readonly done: number | null;
  readonly total: number | null;
  readonly remaining: number | null;
}

const ContinuePromptSchema = z
  .object({
    message: z.string().min(1),
    done: z.number().int().nonnegative().nullable().optional(),
    total: z.number().int().nonnegative().nullable().optional(),
    remaining: z.number().int().nonnegative().nullable().optional(),
  })
  .passthrough();

function decodeJsonLayers(value: unknown, label: string): unknown {
  let decoded = value;
  for (let depth = 0; depth < 2 && typeof decoded === 'string'; depth += 1) {
    try {
      decoded = JSON.parse(decoded) as unknown;
    } catch (error) {
      throw schemaMismatch(`${label} encoded JSON`, error as Error);
    }
  }
  if (typeof decoded === 'string') {
    throw schemaMismatch(
      `${label} encoded JSON`,
      new Error('Content remained encoded after the required second parse.'),
    );
  }
  return decoded;
}

function extractCandidates(value: unknown): unknown[] {
  const decoded = decodeJsonLayers(value, 'pending-change');
  if (Array.isArray(decoded)) {
    return decoded.flatMap(extractCandidates);
  }
  if (decoded !== null && typeof decoded === 'object') {
    const record = decoded as Record<string, unknown>;
    if ('content' in record && !('change_id' in record)) {
      return extractCandidates(record.content);
    }
    if (Array.isArray(record.changes)) {
      return record.changes.flatMap(extractCandidates);
    }
  }
  return [decoded];
}

function toProposedChange(change: PendingChange): ProposedChange {
  return {
    id: change.change_id,
    operation: change.operation,
    chunkId: change.chunk_id ?? null,
    documentId: change.document_id ?? null,
    oldContent: change.old_html ?? null,
    newContent: change.new_html ?? null,
    explanation: change.ai_explanation ?? null,
  };
}

export function normalizePendingChanges(value: unknown): ProposedChange[] {
  const candidates = extractCandidates(value);
  if (candidates.length === 0) {
    throw schemaMismatch(
      'pending changes',
      new Error('The pending-change collection was empty.'),
    );
  }
  return candidates.map((candidate) => {
    const parsed = PendingChangeSchema.safeParse(candidate);
    if (!parsed.success) {
      throw schemaMismatch('pending change', parsed.error);
    }
    return toProposedChange(parsed.data);
  });
}

export function normalizeContinuePrompt(value: unknown): ContinuePrompt {
  const decoded = decodeJsonLayers(value, 'continue-prompt');
  const parsed = ContinuePromptSchema.safeParse(decoded);
  if (!parsed.success) {
    throw schemaMismatch('continue prompt', parsed.error);
  }
  return {
    message: parsed.data.message,
    done: parsed.data.done ?? null,
    total: parsed.data.total ?? null,
    remaining: parsed.data.remaining ?? null,
  };
}
