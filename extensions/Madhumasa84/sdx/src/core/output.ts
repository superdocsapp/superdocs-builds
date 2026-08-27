import { z } from 'zod';

export const OutputStatusSchema = z.enum([
  'completed',
  'unchanged',
  'awaiting_approval',
  'rejected',
  'failed',
]);

const ReferenceSchema = z
  .object({
    id: z.string().min(1),
    name: z.string().min(1).nullable(),
  })
  .strict();

const DocumentSchema = z
  .object({
    id: z.string().min(1).nullable(),
    name: z.string().min(1),
    format: z.string().min(1).nullable(),
    path: z.string().min(1).nullable(),
    outputPath: z.string().min(1).nullable(),
  })
  .strict();

const ChangeSchema = z
  .object({
    id: z.string().min(1),
    operation: z.enum(['edit', 'create', 'delete']).optional(),
    chunkId: z.string().nullable().optional(),
    explanation: z.string().nullable().optional(),
    documentId: z.string().nullable().optional(),
    section: z.string().min(1).nullable(),
    summary: z.string().min(1),
    before: z.string().nullable(),
    after: z.string().nullable(),
    decision: z.enum(['pending', 'approved', 'rejected']),
  })
  .strict();

export const OutputEnvelopeSchema = z
  .object({
    schemaVersion: z.literal('1.0'),
    command: z.string().min(1),
    status: OutputStatusSchema,
    ok: z.boolean(),
    session: ReferenceSchema.nullable(),
    job: ReferenceSchema.nullable(),
    document: DocumentSchema.nullable(),
    changes: z.array(ChangeSchema),
    usage: z
      .object({
        apiCalls: z.number().int().nonnegative(),
        uploadedBytes: z.number().int().nonnegative(),
        downloadedBytes: z.number().int().nonnegative(),
      })
      .strict()
      .nullable(),
    timing: z
      .object({
        startedAt: z.string().datetime(),
        finishedAt: z.string().datetime(),
        durationMs: z.number().nonnegative(),
      })
      .strict(),
    warnings: z.array(z.string()),
    error: z
      .object({
        code: z.string().min(1),
        message: z.string().min(1),
        details: z.unknown().optional(),
      })
      .strict()
      .nullable(),
    data: z.record(z.unknown()).nullable().optional(),
    diagnostics: z
      .array(
        z
          .object({
            name: z.string().min(1),
            status: z.enum(['pass', 'warn', 'fail']),
            message: z.string().min(1),
          })
          .strict(),
      )
      .optional(),
  })
  .strict();

export type OutputEnvelope = z.infer<typeof OutputEnvelopeSchema>;

