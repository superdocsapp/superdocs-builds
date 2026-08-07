export type RetrySafety =
  | 'read'
  | 'signed-download'
  | 'signed-upload'
  | 'nonbillable-write'
  | 'billable-write';

export interface RetryPolicyOptions {
  readonly baseDelayMs?: number;
  readonly maxDelayMs?: number;
  readonly maxAttempts?: number;
  readonly sleeper?: (delayMs: number, signal?: AbortSignal) => Promise<void>;
  readonly clock?: () => number;
  readonly randomness?: () => number;
}

export interface RetryPlan {
  readonly retry: boolean;
  readonly kind: 'application-429' | 'infrastructure-429' | 'transient' | 'none';
  readonly delayMs: number;
  readonly retryAfterSeconds: number | null;
  readonly attempt: number;
  readonly reason: string;
}

export interface ResponseRetryInput {
  readonly status: number;
  readonly retryAfter: string | null;
  readonly contentType: string | null;
  readonly safety: RetrySafety;
  readonly attempt: number;
  readonly deadlineMs: number;
}

const DEFAULT_BASE_DELAY_MS = 250;
const DEFAULT_MAX_DELAY_MS = 5_000;
const DEFAULT_MAX_ATTEMPTS = 4;

function defaultSleep(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(resolve, delayMs);
    const abort = (): void => {
      clearTimeout(timer);
      reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'));
    };
    signal?.addEventListener('abort', abort, { once: true });
  });
}

function retryAfterSeconds(value: string | null): number | null {
  if (value === null || !/^\d+(?:\.\d+)?$/.test(value.trim())) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export class RetryPolicy {
  public readonly baseDelayMs: number;
  public readonly maxDelayMs: number;
  public readonly maxAttempts: number;
  private readonly sleeper: (delayMs: number, signal?: AbortSignal) => Promise<void>;
  private readonly clock: () => number;
  private readonly randomness: () => number;

  public constructor(options: RetryPolicyOptions = {}) {
    this.baseDelayMs = options.baseDelayMs ?? DEFAULT_BASE_DELAY_MS;
    this.maxDelayMs = options.maxDelayMs ?? DEFAULT_MAX_DELAY_MS;
    this.maxAttempts = options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
    this.sleeper = options.sleeper ?? defaultSleep;
    this.clock = options.clock ?? Date.now;
    this.randomness = options.randomness ?? Math.random;
  }

  public now(): number { return this.clock(); }

  public responsePlan(input: ResponseRetryInput): RetryPlan {
    const seconds = retryAfterSeconds(input.retryAfter);
    if (input.status === 429 && seconds !== null) {
      return this.budgetedPlan('application-429', seconds * 1_000, seconds, input.attempt, input.deadlineMs,
        'SuperDocs application rate limit');
    }
    if (input.status === 429 && input.retryAfter === null && !input.contentType?.toLowerCase().includes('application/json')) {
      return this.budgetedPlan('infrastructure-429', this.jitter(input.attempt), null, input.attempt, input.deadlineMs,
        'SuperDocs infrastructure rate limit');
    }
    if ([500, 502, 503].includes(input.status) && this.canRepeatAfterAmbiguity(input.safety)) {
      return this.budgetedPlan('transient', this.jitter(input.attempt), null, input.attempt, input.deadlineMs,
        `transient HTTP ${input.status}`);
    }
    return this.none(input.attempt, 'operation is not safely retryable');
  }

  public transportPlan(safety: RetrySafety, attempt: number, deadlineMs: number): RetryPlan {
    if (!this.canRepeatAfterAmbiguity(safety)) return this.none(attempt, 'ambiguous write outcome');
    return this.budgetedPlan('transient', this.jitter(attempt), null, attempt, deadlineMs, 'transient transport failure');
  }

  public async wait(plan: RetryPlan, signal?: AbortSignal): Promise<void> {
    if (!plan.retry) return;
    await this.sleeper(plan.delayMs, signal);
  }

  private canRepeatAfterAmbiguity(safety: RetrySafety): boolean {
    return safety === 'read' || safety === 'signed-download';
  }

  private jitter(attempt: number): number {
    const ceiling = Math.min(this.maxDelayMs, this.baseDelayMs * (2 ** Math.max(0, attempt - 1)));
    return Math.floor(Math.max(0, Math.min(1, this.randomness())) * ceiling);
  }

  private budgetedPlan(
    kind: RetryPlan['kind'], delayMs: number, seconds: number | null, attempt: number,
    deadlineMs: number, reason: string,
  ): RetryPlan {
    if (attempt >= this.maxAttempts) return this.none(attempt, `${reason}; attempt limit exhausted`, kind, delayMs, seconds);
    if (this.clock() + delayMs > deadlineMs) return this.none(attempt, `${reason}; retry delay exceeds available budget`, kind, delayMs, seconds);
    return { retry: true, kind, delayMs, retryAfterSeconds: seconds, attempt, reason };
  }

  private none(
    attempt: number, reason: string, kind: RetryPlan['kind'] = 'none', delayMs = 0,
    seconds: number | null = null,
  ): RetryPlan {
    return { retry: false, kind, delayMs, retryAfterSeconds: seconds, attempt, reason };
  }
}
