import type { output, ZodTypeAny } from 'zod';

export function parseApiResponse<TSchema extends ZodTypeAny>(
  schema: TSchema,
  payload: unknown,
): output<TSchema> {
  return schema.parse(payload);
}

export interface StreamingUploadRequest {
  readonly contentLength: number;
  readonly contentType: string;
  readonly fileName: string;
  readonly source: NodeJS.ReadableStream;
}

