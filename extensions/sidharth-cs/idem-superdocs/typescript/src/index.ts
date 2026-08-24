/**
 * Idempotency and safe-retry middleware for SuperDocs document operations.
 *
 * Built for the SuperDocs open task list card "Idempotency and safe-retry
 * middleware" (p322, band S3). The written specification is SPEC.md; the
 * decision table is policy.json; the cross-language contract is vectors.json.
 * This implementation and the Python one are written from that specification
 * and verified against those same vectors.
 */

export { Backoff, MalformedPolicy, Policy } from "./policy.ts";
export type { Observation, Outcome, Rule } from "./policy.ts";
export {
  Idempotent,
  OutcomeUnknown,
  RetriesExhausted,
  TerminalFailure,
  UnknownPolicy,
  Verdict,
} from "./runner.ts";
export type { IdempotentOptions, Probe, ProbeAnswer, RunOptions } from "./runner.ts";
export { Store } from "./store.ts";
export type { Record, State } from "./store.ts";
