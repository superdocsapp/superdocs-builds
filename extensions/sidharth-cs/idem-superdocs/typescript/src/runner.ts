/**
 * The middleware: claim a key, attempt the operation, classify what happened,
 * and refuse to guess.
 *
 * This module branches on the four abstract outcomes the table can return —
 * success, retryable, terminal, unknown — and on nothing else. There is no HTTP
 * status code and no error class name anywhere in this file; putting one here
 * is what the build exists to argue against, and a test greps for it
 * (SPEC.md R7).
 */

import type { Policy } from "./policy.ts";
import { FAILED, IN_FLIGHT, SUCCEEDED, Store, type Record } from "./store.ts";

/** What to do when an attempt's outcome cannot be determined. There is no safe
 * default, so the default is to stop and let a human decide.
 *
 * A const object rather than an enum: the package runs under Node's native type
 * stripping, which erases types but does not transform enums. */
export const UnknownPolicy = {
  REFUSE: "refuse",
  RECONCILE: "reconcile",
  RETRY_ANYWAY: "retry_anyway",
} as const;
export type UnknownPolicy = (typeof UnknownPolicy)[keyof typeof UnknownPolicy];

export const Verdict = {
  APPLIED: "applied",
  NOT_APPLIED: "not_applied",
  INCONCLUSIVE: "inconclusive",
} as const;
export type Verdict = (typeof Verdict)[keyof typeof Verdict];

/** The outcome is unknown and nothing authorised a retry. The operation may or
 * may not have been applied; this error is the library declining to guess. */
export class OutcomeUnknown extends Error {
  override name = "OutcomeUnknown";
}

/** The table classified the failure terminal. Retrying will not help. */
export class TerminalFailure extends Error {
  override name = "TerminalFailure";
}

/** The retry budget ran out on a failure that provably never reached the
 * server. The key has been released; a later caller starts genuinely fresh. */
export class RetriesExhausted extends Error {
  override name = "RetriesExhausted";
}

export type ProbeAnswer = Verdict | [Verdict, unknown];
export type Probe = (record: Record) => ProbeAnswer;

export interface RunOptions {
  onUnknown?: UnknownPolicy;
  probe?: Probe;
  naturallyIdempotent?: boolean;
}

export interface IdempotentOptions {
  jobProbe?: (jobId: string) => ProbeAnswer;
  sleep?: (seconds: number) => void;
  random?: () => number;
  extractJobId?: (result: unknown) => string | null;
}

/**
 * Reduce a thrown error to the three things the table can match on.
 *
 * Property lookups only. This never imports an HTTP library, and never compares
 * a status to a literal — it just reports what it found.
 */
function observe(error: any): {
  status: number | null;
  name: string;
  sent: boolean;
  retryAfterMs: number | null;
} {
  const status = error?.status ?? error?.response?.status ?? null;
  return {
    status: typeof status === "number" ? status : null,
    name: error?.constructor?.name ?? typeof error,
    // Absent an explicit attestation, assume the request WAS sent. Assuming
    // otherwise is precisely how a retry library double-applies.
    sent: error?.sent === undefined ? true : Boolean(error.sent),
    retryAfterMs: error?.retryAfterMs ?? error?.retry_after_ms ?? null,
  };
}

function defaultJobId(result: unknown): string | null {
  return result && typeof result === "object" && "job_id" in (result as any)
    ? String((result as any).job_id)
    : null;
}

export class Idempotent {
  readonly store: Store;
  readonly policy: Policy;
  private readonly jobProbe?: (jobId: string) => ProbeAnswer;
  private readonly sleep: (seconds: number) => void;
  private readonly random: () => number;
  private readonly extractJobId: (result: unknown) => string | null;

  constructor(storePath: string, policy: Policy, options: IdempotentOptions = {}) {
    this.store = new Store(storePath);
    this.policy = policy;
    this.jobProbe = options.jobProbe;
    this.sleep = options.sleep ?? (() => {});
    this.random = options.random ?? Math.random;
    this.extractJobId = options.extractJobId ?? defaultJobId;
  }

  // ---- public surface -------------------------------------------------------

  run(key: string, fn: () => unknown, options: RunOptions = {}): unknown {
    const onUnknown = options.onUnknown ?? UnknownPolicy.REFUSE;
    const existing = this.store.claim(key);

    if (existing === null) return this.attemptLoop(key, fn, onUnknown, options);

    if (existing.state === SUCCEEDED) return existing.result; // R3 / N1
    if (existing.state === FAILED) {
      throw new TerminalFailure(existing.detail ?? "operation previously failed terminally");
    }
    if (existing.state === IN_FLIGHT) {
      if (existing.ownedByThisProcess) {
        throw new OutcomeUnknown(`key '${key}' is held by another caller in this process`);
      }
      // The owning process is gone, or is another live process. Both are unsafe
      // to execute and neither is distinguishable from here, so fail closed:
      // this becomes an unknown outcome (N4).
      this.store.markUnknown(key, `in-flight record left by pid ${existing.ownerPid}`);
    }

    return this.resolveUnknown(key, fn, onUnknown, options);
  }

  /**
   * Ask what actually happened. Public and callable on its own (SPEC.md R13).
   *
   * Returns APPLIED (record becomes succeeded, the function is never re-run),
   * NOT_APPLIED (the key is released and may be retried), or INCONCLUSIVE (the
   * record stays unknown and stays refused).
   */
  reconcile(key: string, probe?: Probe): Verdict {
    const record = this.store.get(key);
    if (record === null) return Verdict.INCONCLUSIVE;
    if (record.state === SUCCEEDED) return Verdict.APPLIED;

    const answer = this.ask(record, probe);
    const [verdict, result] = Array.isArray(answer) ? answer : [answer, undefined];

    if (verdict === Verdict.APPLIED) {
      this.store.succeed(key, result === undefined ? record.result : result);
    } else if (verdict === Verdict.NOT_APPLIED) {
      // Same invariant as a retryable outcome: provably not applied, so
      // releasing the key cannot cause a double-apply (SPEC.md R10).
      this.store.release(key);
    }
    return verdict;
  }

  // ---- internals ------------------------------------------------------------

  private ask(record: Record, probe?: Probe): ProbeAnswer {
    if (probe) return probe(record);
    // The documented limit (SPEC.md 6): with no job id bound and no job probe
    // configured, there is nothing to ask, and "I could not find out" must
    // never be mistaken for "it did not happen".
    if (!this.jobProbe || record.jobId === null) return Verdict.INCONCLUSIVE;
    return this.jobProbe(record.jobId);
  }

  /** An unknown outcome is never retried without an explicit policy choice
   * (SPEC.md R12). This is the only place that choice is honoured. */
  private resolveUnknown(
    key: string,
    fn: () => unknown,
    onUnknown: UnknownPolicy,
    options: RunOptions,
    spent = 0,
  ): unknown {
    const detail = this.store.get(key)?.detail ?? "outcome unknown";

    if (onUnknown === UnknownPolicy.REFUSE) {
      throw new OutcomeUnknown(
        `${detail}; the operation may or may not have been applied. ` +
          `Reconcile it, or choose a policy explicitly.`,
      );
    }

    if (onUnknown === UnknownPolicy.RECONCILE) {
      const verdict = this.reconcile(key, options.probe);
      if (verdict === Verdict.APPLIED) return this.store.get(key)!.result;
      if (verdict === Verdict.INCONCLUSIVE) {
        throw new OutcomeUnknown(`${detail}; reconciliation was inconclusive`);
      }
    } else if (onUnknown === UnknownPolicy.RETRY_ANYWAY) {
      if (!options.naturallyIdempotent) {
        throw new OutcomeUnknown(
          "UnknownPolicy.RETRY_ANYWAY also requires naturallyIdempotent: true. " +
            "Retrying an unknown outcome is only sound when repeating the operation " +
            "cannot change the result, and only the caller knows that.",
        );
      }
      console.warn(
        `idem: retrying key '${key}' after an unknown outcome (${detail}) because ` +
          `the caller asserted the operation is naturally idempotent`,
      );
      this.store.release(key);
    }

    // Reconciliation said not-applied, or the caller vouched for the operation.
    // Either way the key is released and a fresh attempt is now justified rather
    // than assumed.
    this.store.claim(key);
    // The delay belongs to the attempt that just failed, not the next one, so
    // back off by one from the running count.
    this.pause(Math.max(0, spent - 1), null);
    return this.attemptLoop(key, fn, onUnknown, options, spent);
  }

  /**
   * `spent` is the number of attempts this run() has already made, including
   * those made before an unknown outcome was resolved.
   *
   * It has to be threaded through rather than recomputed from the record,
   * because resolving an unknown releases the key and that resets the record's
   * own count. Without it, every reconcile-says-not-applied starts a fresh
   * budget and run() can loop forever — the exact unbounded retry this library
   * exists to prevent. Found by the Python fuzzer, pinned as vector V19, and
   * that vector caught the identical bug here.
   */
  private attemptLoop(
    key: string,
    fn: () => unknown,
    onUnknown: UnknownPolicy,
    options: RunOptions,
    spent = 0,
  ): unknown {
    const budget = this.policy.backoff.maxAttempts;

    for (let attempt = spent; attempt < budget; attempt++) {
      this.store.recordAttempt(key);
      let result: unknown;
      try {
        result = fn();
      } catch (error: any) {
        const { status, name, sent, retryAfterMs } = observe(error);
        const rule = this.policy.classify({ status, error: name, sent });

        if (rule.outcome === "retryable") {
          if (attempt === budget - 1) {
            this.store.release(key);
            throw new RetriesExhausted(
              `${budget} attempts on key '${key}', last: ${rule.id} (${error})`,
            );
          }
          this.pause(attempt, rule.honourRetryAfter ? retryAfterMs : null);
          continue;
        }

        if (rule.outcome === "terminal") {
          this.store.fail(key, `${rule.id}: ${error}`);
          throw new TerminalFailure(`${rule.id}: ${rule.why}`);
        }

        this.store.markUnknown(key, `${rule.id}: ${error}`);
        if (attempt === budget - 1) {
          // The budget is spent. An unknown outcome stays unknown rather than
          // silently becoming another attempt.
          throw new OutcomeUnknown(
            `${rule.id}: ${error}; the retry budget is exhausted and the outcome is ` +
              `still unknown. Reconcile key '${key}' before retrying.`,
          );
        }
        return this.resolveUnknown(key, fn, onUnknown, options, attempt + 1);
      }

      const jobId = this.extractJobId(result);
      if (jobId !== null) this.store.bindJob(key, jobId);
      this.store.succeed(key, result);
      return result;
    }

    throw new RetriesExhausted(`retry budget exhausted on key '${key}'`);
  }

  private pause(attempt: number, retryAfterMs: number | null): void {
    const delayMs =
      retryAfterMs !== null
        ? retryAfterMs
        : this.policy.backoff.delayMs(attempt, this.random);
    this.sleep(delayMs / 1000);
  }
}
