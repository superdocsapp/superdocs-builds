/**
 * Shared machinery: the scripted operation, the fake server, and the paths to
 * the two data files both implementations read.
 */

import { appendFileSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { Idempotent, Policy, Verdict } from "../src/index.ts";

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const POLICY_PATH = join(ROOT, "policy.json");
export const VECTORS_PATH = join(ROOT, "vectors.json");

export function loadVectors(): any[] {
  return JSON.parse(readFileSync(VECTORS_PATH, "utf8")).vectors;
}

export function loadPolicy(): Policy {
  return Policy.load(POLICY_PATH);
}

export function tempDir(): string {
  return mkdtempSync(join(tmpdir(), "idem-"));
}

/**
 * An error shaped the way the library reads errors: a status if there was a
 * response, and an explicit attestation of whether the request was sent.
 *
 * The class is built with the name the vector asks for, so the vectors stay
 * honest about matching on the error's *name* rather than on its identity.
 */
export function scriptedError(
  className: string,
  status?: number | null,
  sent = true,
  retryAfterMs?: number | null,
): Error {
  const Named = { [className]: class extends Error {} }[className]!;
  const error: any = new Named(`${className}(status=${status}, sent=${sent})`);
  error.status = status ?? null;
  error.sent = sent;
  error.retryAfterMs = retryAfterMs ?? null;
  return error;
}

/** Consumes a vector's attempt script. Counts executions, because 'executions'
 * is the observable form of 'did we double-apply'. */
export class ScriptedOperation {
  executions = 0;
  private readonly script: any[];

  constructor(attempts: any[]) {
    this.script = [...attempts];
  }

  run = (): unknown => {
    this.executions += 1;
    const step = this.script.shift();
    if (!step) {
      throw new Error(
        `the operation ran ${this.executions} times but the vector only ` +
          `scripted ${this.executions - 1} attempts`,
      );
    }
    if (step.event === "ok") return step.result ?? null;
    throw scriptedError(step.class, step.status, step.sent ?? true, step.retry_after_ms);
  };
}

/** An Idempotent whose sleeps are captured rather than taken, so the suite is
 * deterministic and never actually waits. */
export function build(dir: string, policy?: Policy, jobProbe?: any) {
  const delaysMs: number[] = [];
  let seed = 1234;
  const idem = new Idempotent(join(dir, "idem.db"), policy ?? loadPolicy(), {
    jobProbe,
    sleep: (seconds) => delaysMs.push(seconds * 1000),
    // A small deterministic generator, so a failing run is reproducible. The
    // vectors assert bounds rather than values, so the exact sequence is
    // deliberately not part of the contract (SPEC.md R11).
    random: () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    },
  });
  return { idem, delaysMs };
}

// ---- the fake server --------------------------------------------------------
//
// Mirrors tests/fakeserver.py exactly, including the append-only log: a
// read-modify-write counter could lose an increment under the concurrency this
// harness exists to test, and a lost increment is a double-apply that goes
// unreported.

export class LostResponse extends Error {
  override name = "LostResponse";
  sent = true;
}

export class Conflict extends Error {
  override name = "Conflict";
  status = 409;
  sent = true;
}

export class FakeServer {
  readonly log: string;

  constructor(path: string) {
    this.log = path;
    try {
      readFileSync(this.log);
    } catch {
      writeFileSync(this.log, "");
    }
  }

  private entries(): any[] {
    return readFileSync(this.log, "utf8")
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line));
  }

  /** How many edits this server actually performed. */
  get applies(): number {
    return this.entries().filter((e) => e.kind === "edit").length;
  }

  /** How many approvals this server actually recorded. The Review-surface
   * equivalent of `applies`: approving twice is as wrong as editing twice. */
  get approvals(): number {
    return this.entries().filter((e) => e.kind === "approve").length;
  }

  /** The Review job lifecycle as the server sees it. A job that was approved
   * but whose approval never settled stays `awaiting_approval` — which is bug 5
   * exactly: the approve call returned success and the job never moved. */
  jobStatus(jobId: string): string {
    const approvals = this.entries().filter((e) => e.kind === "approve" && e.job_id === jobId);
    return approvals.some((a) => a.settled) ? "completed" : "awaiting_approval";
  }

  /** Decide a proposed change. Recording the approval IS the apply — it is the
   * billable, state-changing half of the Review flow. `settles: false`
   * reproduces the wedge: the call succeeds and the job never settles. */
  approve(operationKey: string, jobId: string,
          opts: { loseResponse?: boolean; settles?: boolean } = {}) {
    const settles = opts.settles ?? true;
    appendFileSync(this.log, JSON.stringify({
      kind: "approve", job_id: jobId, operation_key: operationKey,
      settled: settles, status: settles ? "completed" : "awaiting_approval",
    }) + "\n");

    if (opts.loseResponse) {
      throw new LostResponse(`approval of ${jobId} recorded, response never arrived`);
    }
    return { job_id: jobId, batch_complete: settles };
  }

  /** How many times one specific key was applied. The per-key form of the
   * assertion the whole harness is built around. */
  appliesFor(operationKey: string): number {
    return this.entries().filter((e) => e.kind === "edit" && e.operation_key === operationKey).length;
  }

  findByOperationKey(operationKey: string): any | null {
    return this.entries().find((e) => e.operation_key === operationKey) ?? null;
  }

  /** Apply an edit, then optionally lose the answer on the way back. The apply
   * is recorded *before* the response is lost, which is what makes the
   * partition scenario a real test. */
  chatAsync(operationKey: string, opts: { loseResponse?: boolean; conflict?: boolean } = {}) {
    if (opts.conflict) throw new Conflict("session state rejects this call");

    const job = {
      kind: "edit",
      job_id: `job-${operationKey}-${this.applies + 1}`,
      status: "completed",
      operation_key: operationKey,
    };
    appendFileSync(this.log, JSON.stringify(job) + "\n"); // O_APPEND: atomic

    if (opts.loseResponse) {
      throw new LostResponse(`applied as ${job.job_id}, response never arrived`);
    }
    return job;
  }
}

export function probeReturning(vector: any) {
  if (!vector.reconcile_verdict) return undefined;
  const verdict = vector.reconcile_verdict as Verdict;
  const result = vector.reconcile_result;
  return () => (result !== undefined ? ([verdict, result] as [Verdict, unknown]) : verdict);
}
