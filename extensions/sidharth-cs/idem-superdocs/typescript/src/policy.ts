/**
 * The decision table, loaded from data.
 *
 * Nothing in this module knows which status code means a conflict, or which
 * error name means the answer was lost. It knows how to match an observation
 * against a rule and how to compute a jittered delay. Every judgement lives in
 * policy.json — the same file the Python implementation loads (SPEC.md R6, R7).
 *
 * Deliberately so: a test greps this file and the runner for status-code
 * literals and error class names, and fails if it finds any.
 */

import { readFileSync } from "node:fs";

export const OUTCOMES = ["success", "retryable", "terminal", "unknown"] as const;
export type Outcome = (typeof OUTCOMES)[number];

const CONDITIONS = ["status", "status_range", "error", "sent"] as const;

export class MalformedPolicy extends Error {}

export interface Rule {
  id: string;
  outcome: Outcome;
  why: string;
  honourRetryAfter: boolean;
  requiresReconciliation: boolean;
}

interface When {
  status?: number;
  status_range?: [number, number];
  error?: string;
  sent?: boolean;
}

export interface Observation {
  status: number | null;
  error: string;
  sent: boolean;
}

export class Backoff {
  readonly baseMs: number;
  readonly maxMs: number;
  readonly multiplier: number;
  readonly maxAttempts: number;

  constructor(baseMs: number, maxMs: number, multiplier: number, maxAttempts: number) {
    this.baseMs = baseMs;
    this.maxMs = maxMs;
    this.multiplier = multiplier;
    this.maxAttempts = maxAttempts;
  }

  /**
   * The upper bound for this attempt's delay. Public because the test vectors
   * assert against it: seeded RNGs are not portable between languages, so
   * vectors check the bound rather than the value (SPEC.md R11).
   */
  ceilingMs(attempt: number): number {
    return Math.min(this.maxMs, this.baseMs * this.multiplier ** attempt);
  }

  delayMs(attempt: number, random: () => number): number {
    // Full jitter. Equal and decorrelated jitter both keep a floor under the
    // delay, which re-synchronises clients that failed together.
    return random() * this.ceilingMs(attempt);
  }
}

export class Policy {
  readonly backoff: Backoff;
  private readonly rules: Array<[When, Rule]>;

  constructor(raw: any) {
    Policy.validate(raw);
    const b = raw.backoff;
    this.backoff = new Backoff(
      Number(b.base_ms),
      Number(b.max_ms),
      Number(b.multiplier),
      Number(b.max_attempts),
    );
    this.rules = raw.rules.map((r: any): [When, Rule] => [
      r.when,
      {
        id: r.id,
        outcome: r.outcome,
        why: r.why ?? "",
        honourRetryAfter: Boolean(r.honour_retry_after),
        requiresReconciliation: Boolean(r.requires_reconciliation),
      },
    ]);
  }

  static load(path: string): Policy {
    return new Policy(JSON.parse(readFileSync(path, "utf8")));
  }

  private static validate(raw: any): void {
    if (raw?.version !== 1) {
      throw new MalformedPolicy(`unsupported policy version: ${raw?.version}`);
    }
    const rules = raw.rules;
    if (!rules?.length) throw new MalformedPolicy("policy has no rules");
    for (const r of rules) {
      if (!OUTCOMES.includes(r.outcome)) {
        throw new MalformedPolicy(`rule ${r.id}: outcome must be one of ${OUTCOMES.join(", ")}`);
      }
      for (const key of Object.keys(r.when ?? {})) {
        if (!CONDITIONS.includes(key as any)) {
          throw new MalformedPolicy(`rule ${r.id}: unknown condition '${key}'`);
        }
      }
      // The card asks for every decision documented with its reasoning. A rule
      // that classifies a failure without saying why is the thing this build
      // exists to replace, so the loader refuses it.
      if (r.outcome !== "success" && !r.why) {
        throw new MalformedPolicy(`rule ${r.id}: every non-success rule needs a 'why'`);
      }
    }
    if (Object.keys(rules.at(-1).when ?? {}).length !== 0) {
      throw new MalformedPolicy("the last rule must be a catch-all with an empty 'when'");
    }
  }

  /** First rule whose every condition matches. The catch-all guarantees this
   * always returns. */
  classify(observation: Observation): Rule {
    for (const [when, rule] of this.rules) {
      if (Policy.matches(when, observation)) return rule;
    }
    throw new MalformedPolicy("no rule matched and no catch-all fired");
  }

  private static matches(when: When, o: Observation): boolean {
    if (when.status !== undefined && o.status !== when.status) return false;
    if (when.status_range !== undefined) {
      const [lo, hi] = when.status_range;
      if (o.status === null || o.status < lo || o.status > hi) return false;
    }
    if (when.error !== undefined && o.error !== when.error) return false;
    if (when.sent !== undefined && o.sent !== when.sent) return false;
    return true;
  }
}
