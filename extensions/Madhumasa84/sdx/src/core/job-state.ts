import { EXIT_CODES } from './exit-codes.js';
import { SdxError, schemaMismatch } from '../api/errors.js';
import type { ApiJob } from '../api/schemas.js';
import type { SuperDocsClient } from '../api/client.js';
import {
  normalizeContinuePrompt,
  normalizePendingChanges,
  type ContinuePrompt,
  type ProposedChange,
} from './changes.js';

export interface PollOptions {
  readonly intervalMs: number;
  readonly timeoutMs: number;
  readonly signal: AbortSignal | undefined;
  readonly onProgress: ((job: ApiJob) => void) | undefined;
}

export type PollResult =
  | { readonly kind: 'completed'; readonly job: ApiJob }
  | {
      readonly kind: 'approval';
      readonly job: ApiJob;
      readonly changes: readonly ProposedChange[];
    }
  | {
      readonly kind: 'continuation';
      readonly job: ApiJob;
      readonly prompt: ContinuePrompt;
    };

function wait(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted === true) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(resolve, milliseconds);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(new DOMException('Aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

export async function pollUntilAction(
  client: Pick<SuperDocsClient, 'getJob'>,
  jobId: string,
  options: PollOptions,
): Promise<PollResult> {
  const deadline = Date.now() + options.timeoutMs;

  while (true) {
    if (options.signal?.aborted === true) {
      throw new SdxError('Operation interrupted by the user.', EXIT_CODES.interrupted);
    }
    if (Date.now() >= deadline) {
      throw new SdxError(
        `Job ${jobId} did not reach an actionable state within ${options.timeoutMs}ms.`,
        EXIT_CODES.apiFailure,
      );
    }

    const job = await client.getJob(jobId, options.signal);
    options.onProgress?.(job);
    switch (job.status) {
      case 'pending':
      case 'in_progress':
        await wait(options.intervalMs, options.signal);
        break;
      case 'awaiting_approval': {
        const metadata = job.metadata;
        if (metadata?.awaiting_kind === 'continue_prompt') {
          if (metadata.continue_prompt === undefined) {
            throw schemaMismatch(
              'continue-prompt job',
              new Error('metadata.continue_prompt is missing.'),
            );
          }
          return {
            kind: 'continuation',
            job,
            prompt: normalizeContinuePrompt(metadata.continue_prompt),
          };
        }
        if (metadata?.pending_changes === undefined) {
          throw schemaMismatch(
            'awaiting-approval job',
            new Error('metadata.pending_changes is missing.'),
          );
        }
        return {
          kind: 'approval',
          job,
          changes: normalizePendingChanges(metadata.pending_changes),
        };
      }
      case 'completed':
        return { kind: 'completed', job };
      case 'failed':
        throw new SdxError(
          `SuperDocs job failed${job.error ? `: ${job.error}` : '.'}`,
          EXIT_CODES.apiFailure,
        );
      case 'cancelled':
        throw new SdxError('SuperDocs job was cancelled.', EXIT_CODES.apiFailure);
    }
  }
}
