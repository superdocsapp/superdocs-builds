import { z } from 'zod';

export const UploadUrlResponseSchema = z
  .object({
    upload_id: z.string().min(1),
    upload_url: z.string().url(),
    expires_at: z.string().min(1),
    expires_in_seconds: z.number().int().positive(),
    max_size_bytes: z.number().int().positive(),
    curl_example: z.string(),
  })
  .passthrough();

export const ProcessDocumentResponseSchema = z
  .object({
    html: z.string().nullable().optional(),
    session_id: z.string().min(1),
    filename: z.string().min(1),
    chunks_count: z.number().int().nonnegative().nullable().optional(),
    version_id: z.string().nullable().optional(),
    job_id: z.string().nullable().optional(),
    document_id: z.string().nullable().optional(),
    durable_document_id: z.string().nullable().optional(),
    status: z.string().min(1),
    parse_mode: z.string().min(1),
    page_setup: z.record(z.unknown()).nullable().optional(),
    warnings: z.array(z.record(z.unknown())).nullable().optional(),
  })
  .passthrough();

export const AsyncChatResponseSchema = z
  .object({
    job_id: z.string().min(1),
    session_id: z.string().min(1),
    status: z.literal('pending'),
    message: z.string().optional(),
  })
  .passthrough();

export const JobStatusSchema = z.enum([
  'pending',
  'in_progress',
  'awaiting_approval',
  'completed',
  'failed',
  'cancelled',
]);

export const PendingChangeSchema = z
  .object({
    change_id: z.string().min(1),
    operation: z.enum(['edit', 'create', 'delete']),
    chunk_id: z.string().nullable().optional(),
    document_id: z.string().nullable().optional(),
    old_html: z.string().nullable().optional(),
    new_html: z.string().nullable().optional(),
    ai_explanation: z.string().nullable().optional(),
  })
  .passthrough();

const DocumentChangesSchema = z
  .object({
    updated_html: z.string().nullable().optional(),
    version_id: z.string().nullable().optional(),
    changes_summary: z.string().nullable().optional(),
    requires_approval: z.boolean().nullable().optional(),
    pending_changes: z.array(PendingChangeSchema).nullable().optional(),
    changes: z.array(z.record(z.unknown())).nullable().optional(),
    chunk_diffs: z.array(PendingChangeSchema).nullable().optional(),
  })
  .passthrough();

const UsageInfoSchema = z
  .object({
    monthly_used: z.number().int().nullable().optional(),
    monthly_limit: z.number().int().nullable().optional(),
    monthly_remaining: z.number().int().nullable().optional(),
    was_billable: z.boolean().nullable().optional(),
    ops_charged: z.number().int().nullable().optional(),
  })
  .passthrough();

const JobResultSchema = z
  .object({
    response: z.string().nullable().optional(),
    session_id: z.string().nullable().optional(),
    document_changes: DocumentChangesSchema.nullable().optional(),
    usage: UsageInfoSchema.nullable().optional(),
  })
  .passthrough();

const JobMetadataSchema = z
  .object({
    pending_changes: z.unknown().optional(),
    awaiting_kind: z.string().nullable().optional(),
    continue_prompt: z.unknown().optional(),
    intermediate_responses: z.array(z.record(z.unknown())).nullable().optional(),
  })
  .passthrough();

export const JobResponseSchema = z
  .object({
    job_id: z.string().min(1),
    session_id: z.string().min(1),
    job_type: z.string().min(1),
    status: JobStatusSchema,
    created_at: z.string().min(1),
    updated_at: z.string().min(1),
    progress: z.number().int().min(0).max(100),
    result: JobResultSchema.nullable().optional(),
    error: z.string().nullable().optional(),
    metadata: JobMetadataSchema.nullable().optional(),
  })
  .passthrough();

export const ApprovalResponseSchema = z.record(z.unknown());
export const ContinueResponseSchema = z.record(z.unknown());

export const DownloadUrlResponseSchema = z
  .object({
    download_url: z.string().url(),
    expires_at: z.string().min(1),
    expires_in_seconds: z.number().int().positive(),
    curl_example: z.string(),
    filename: z.string().min(1),
    format: z.enum(['docx', 'pdf', 'html', 'markdown', 'txt', 'doc']),
  })
  .passthrough();

export const ExportFormatSchema = z.enum([
  'docx',
  'pdf',
  'html',
  'markdown',
  'txt',
]);

export const ApiErrorBodySchema = z
  .object({
    detail: z.unknown().optional(),
    error_code: z.string().optional(),
    message_user: z.string().optional(),
  })
  .passthrough();

export type UploadUrlResponse = z.infer<typeof UploadUrlResponseSchema>;
export type ProcessDocumentResponse = z.infer<typeof ProcessDocumentResponseSchema>;
export type AsyncChatResponse = z.infer<typeof AsyncChatResponseSchema>;
export type ApiJob = z.infer<typeof JobResponseSchema>;
export type PendingChange = z.infer<typeof PendingChangeSchema>;
export type ExportFormat = z.infer<typeof ExportFormatSchema>;
export type DownloadUrlResponse = z.infer<typeof DownloadUrlResponseSchema>;
