/**
 * The nevers from SPEC.md section 1, one test each — the same nevers the Python
 * suite proves, checked against this implementation.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import {
  Idempotent,
  MalformedPolicy,
  OutcomeUnknown,
  Policy,
  RetriesExhausted,
  TerminalFailure,
  UnknownPolicy,
  Verdict,
} from "../src/index.ts";
import { POLICY_PATH, ROOT, ScriptedOperation, build, loadPolicy, tempDir } from "./harness.ts";

const SOURCE_DIR = join(ROOT, "typescript", "src");

// ---- N1: never execute the same operation key twice -------------------------

test("N1 a completed key replays its recorded result", () => {
  const { idem } = build(tempDir());
  let calls = 0;
  const operation = () => {
    calls += 1;
    return { job_id: "j-1", applied: true };
  };

  const first = idem.run("edit-para-7", operation);
  const second = idem.run("edit-para-7", operation);
  const third = idem.run("edit-para-7", () => {
    throw new Error("must not execute");
  });

  assert.deepEqual(first, second);
  assert.deepEqual(second, third);
  assert.equal(calls, 1, "the operation ran more than once for one key");
});

test("N1 the guard is the key, not the function", () => {
  const { idem } = build(tempDir());
  let calls = 0;
  const operation = () => ({ job_id: `j-${++calls}` });

  idem.run("edit-para-7", operation);
  idem.run("edit-para-8", operation);
  assert.equal(calls, 2);
});

// ---- N2: never retry an unknown outcome without an explicit policy ----------

test("N2 an unknown outcome refuses by default", () => {
  const { idem } = build(tempDir());
  const op = new ScriptedOperation([{ event: "error", class: "ReadTimeout", sent: true }]);

  assert.throws(() => idem.run("timed-out", op.run), OutcomeUnknown);
  assert.equal(op.executions, 1);
  assert.equal(idem.store.stateOf("timed-out"), "unknown");
});

test("N2 the refusal does not wear down under repeated calls", () => {
  const { idem } = build(tempDir());
  const op = new ScriptedOperation([{ event: "error", class: "ReadTimeout", sent: true }]);

  for (let i = 0; i < 5; i++) {
    assert.throws(() => idem.run("timed-out", op.run), OutcomeUnknown);
  }
  assert.equal(op.executions, 1);
});

test("N2 retry-anyway needs the caller to vouch for the operation", () => {
  const { idem } = build(tempDir());
  const op = new ScriptedOperation([{ event: "error", class: "ReadTimeout", sent: true }]);

  assert.throws(
    () => idem.run("timed-out", op.run, { onUnknown: UnknownPolicy.RETRY_ANYWAY }),
    /naturallyIdempotent/,
  );
  assert.equal(op.executions, 1);
});

// ---- N3: never report a success it did not observe --------------------------

const FAILURES: Array<[any, any, string]> = [
  [{ event: "error", class: "ReadTimeout", sent: true }, OutcomeUnknown, "unknown"],
  [{ event: "error", class: "X", status: 503, sent: true }, OutcomeUnknown, "unknown"],
  [{ event: "error", class: "X", status: 409, sent: true }, TerminalFailure, "failed"],
  [{ event: "error", class: "X", status: 422, sent: true }, TerminalFailure, "failed"],
  [{ event: "error", class: "Nobody", sent: true }, OutcomeUnknown, "unknown"],
];

for (const [failure, expectedError, expectedState] of FAILURES) {
  test(`N3 no success state after ${failure.class}/${failure.status ?? "-"}`, () => {
    const { idem } = build(tempDir());
    const op = new ScriptedOperation([failure]);

    assert.throws(() => idem.run("k", op.run), expectedError);
    assert.equal(idem.store.stateOf("k"), expectedState);
    assert.equal(idem.store.get("k")!.result, null);
  });
}

test("N3 an inconclusive reconciliation is not a success", () => {
  const { idem } = build(tempDir());
  const op = new ScriptedOperation([{ event: "error", class: "ReadTimeout", sent: true }]);

  assert.throws(
    () =>
      idem.run("k", op.run, {
        onUnknown: UnknownPolicy.RECONCILE,
        probe: () => Verdict.INCONCLUSIVE,
      }),
    OutcomeUnknown,
  );
  assert.equal(idem.store.stateOf("k"), "unknown");
  assert.equal(op.executions, 1);
});

test("N3 reconciling with no job id and no probe is inconclusive", () => {
  const { idem } = build(tempDir());
  const op = new ScriptedOperation([{ event: "error", class: "ReadTimeout", sent: true }]);

  assert.throws(() => idem.run("k", op.run), OutcomeUnknown);
  assert.equal(idem.reconcile("k"), Verdict.INCONCLUSIVE);
  assert.equal(idem.store.stateOf("k"), "unknown");
});

// ---- N5: never retry a failure the table marks terminal ---------------------

test("N5 a terminal failure is not retried and is not backed off", () => {
  const { idem, delaysMs } = build(tempDir());
  const op = new ScriptedOperation([{ event: "error", class: "X", status: 409, sent: true }]);

  assert.throws(() => idem.run("wedged", op.run), TerminalFailure);
  assert.equal(op.executions, 1, "a terminal failure was retried");
  assert.deepEqual(delaysMs, [], "the library backed off before a failure it should not retry");
});

test("N5 a terminal record refuses without executing", () => {
  const { idem } = build(tempDir());
  const op = new ScriptedOperation([{ event: "error", class: "X", status: 409, sent: true }]);

  assert.throws(() => idem.run("wedged", op.run), TerminalFailure);
  assert.throws(
    () =>
      idem.run("wedged", () => {
        throw new Error("must not execute");
      }),
    TerminalFailure,
  );
  assert.equal(op.executions, 1);
});

test("exhaustion releases the key but a terminal failure does not", () => {
  const { idem } = build(tempDir());

  const exhausted = new ScriptedOperation(
    Array.from({ length: 5 }, () => ({ event: "error", class: "ConnectTimeout", sent: false })),
  );
  assert.throws(() => idem.run("flaky", exhausted.run), RetriesExhausted);
  assert.equal(idem.store.stateOf("flaky"), "new");

  const terminal = new ScriptedOperation([{ event: "error", class: "X", status: 409, sent: true }]);
  assert.throws(() => idem.run("wedged", terminal.run), TerminalFailure);
  assert.equal(idem.store.stateOf("wedged"), "failed");
});

// ---- R1: the library never invents a key ------------------------------------

test("R1 the library never generates a key", () => {
  const { idem } = build(tempDir());
  idem.run("mine-1", () => ({ job_id: "a" }));
  idem.run("mine-2", () => ({ job_id: "b" }));

  assert.deepEqual(idem.store.keys().sort(), ["mine-1", "mine-2"]);

  for (const file of ["policy.ts", "store.ts", "runner.ts", "index.ts"]) {
    const text = readFileSync(join(SOURCE_DIR, file), "utf8");
    assert.ok(!text.includes("randomUUID"), `${file} can generate identifiers`);
    assert.ok(!text.includes("node:crypto"), `${file} can generate identifiers`);
  }
});

// ---- R7: the policy is data, not conditionals -------------------------------

test("R7 the policy is data, not conditionals scattered through the code", () => {
  const raw = JSON.parse(readFileSync(POLICY_PATH, "utf8"));
  const errorNames: string[] = raw.rules
    .filter((r: any) => r.when.error !== undefined)
    .map((r: any) => r.when.error);
  assert.ok(errorNames.length, "the table names no error classes, so this test proves nothing");

  for (const file of ["runner.ts", "policy.ts"]) {
    const code = readFileSync(join(SOURCE_DIR, file), "utf8")
      .split("\n")
      .map((line) => line.replace(/\/\/.*$/, "").replace(/^\s*\*.*$/, ""))
      .join("\n");

    const found = code.match(/\b[2-5]\d\d\b/g);
    assert.equal(found, null, `${file} contains status-code literals: ${found}`);
    for (const name of errorNames) {
      assert.ok(!code.includes(name), `${file} names the error class '${name}'`);
    }
  }
});

test("the table refuses to load an undocumented decision", () => {
  const raw = JSON.parse(readFileSync(POLICY_PATH, "utf8"));
  for (const rule of raw.rules) if (rule.id === "conflict") delete rule.why;
  const path = join(tempDir(), "bad.json");
  writeFileSync(path, JSON.stringify(raw));

  assert.throws(() => Policy.load(path), /why/);
});

test("the table refuses to load without a catch-all", () => {
  const raw = JSON.parse(readFileSync(POLICY_PATH, "utf8"));
  raw.rules = raw.rules.filter((r: any) => Object.keys(r.when).length !== 0);
  const path = join(tempDir(), "bad.json");
  writeFileSync(path, JSON.stringify(raw));

  assert.throws(() => Policy.load(path), MalformedPolicy);
});

test("an unattested failure is assumed sent", () => {
  const { idem } = build(tempDir());
  let calls = 0;

  assert.throws(
    () =>
      idem.run("bare", () => {
        calls += 1;
        throw new Error("something went wrong and said nothing useful");
      }),
    OutcomeUnknown,
  );
  assert.equal(calls, 1);
});

// ---- R11: the backoff is actually jittered ----------------------------------
//
// Found by mutation testing, not by design. The behavioural vectors assert
// 0 <= delay <= ceiling, and a constant delay === ceiling satisfies that — so
// deleting the jitter entirely left the whole suite green. The card asks for
// jittered backoff specifically, and "within bounds" does not mean "jittered".
//
// A distribution test rather than a value test, so it stays portable: the
// vectors still cannot pin an RNG, but they can pin the shape it must produce.

function sampleDelays(n = 400, attempt = 3) {
  const policy = loadPolicy();
  let seed = 20260823;
  const random = () => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed / 2147483648;
  };
  const delays = Array.from({ length: n }, () => policy.backoff.delayMs(attempt, random));
  return { delays, ceiling: policy.backoff.ceilingMs(attempt) };
}

test("R11 the backoff is not a constant", () => {
  // The mutation that got through: return the ceiling every time. Under full
  // jitter 400 draws are essentially all distinct; a constant scores 1.
  const { delays } = sampleDelays();
  assert.ok(new Set(delays).size > 200, "the backoff is not varying — the jitter is gone");
});

test("R11 the backoff spreads across its whole range", () => {
  // Full jitter draws from [0, ceiling]. Equal and decorrelated jitter both keep
  // a floor under the delay, which re-synchronises clients that failed together,
  // so the low end must be reachable. P(no draw below 10% in 400) = 0.9**400.
  const { delays, ceiling } = sampleDelays();
  assert.ok(Math.min(...delays) < ceiling * 0.1, "not full jitter — nothing drawn near zero");
  assert.ok(Math.max(...delays) <= ceiling);
  assert.ok(Math.max(...delays) > ceiling * 0.9, "the top of the range is never reached");
});

test("R11 the backoff mean matches full jitter", () => {
  // Uniform(0, C) has mean C/2. Over 400 draws the standard error is about
  // 0.014C, so +/-8% is roughly six sigma: tight enough to reject a different
  // jitter strategy, wide enough never to flake.
  const { delays, ceiling } = sampleDelays();
  const mean = delays.reduce((a, b) => a + b, 0) / delays.length;
  assert.ok(
    mean > 0.42 * ceiling && mean < 0.58 * ceiling,
    `mean delay ${mean.toFixed(0)}ms is not half the ${ceiling}ms ceiling; not full jitter`,
  );
});

// ---- N3: a NOT_APPLIED verdict is not a success -----------------------------
//
// Found by mutation testing: making reconcile() treat every non-inconclusive
// verdict as APPLIED left this suite green, where the Python suite caught it.
// A gap in the tests, not in the code — and exactly the kind the second
// implementation exists to surface.

test("N3 a NOT_APPLIED verdict releases the key, it does not succeed it", () => {
  const { idem } = build(tempDir());
  const op = new ScriptedOperation([{ event: "error", class: "ReadTimeout", sent: true }]);

  assert.throws(() => idem.run("k", op.run), OutcomeUnknown);
  assert.equal(idem.store.stateOf("k"), "unknown");

  const verdict = idem.reconcile("k", () => Verdict.NOT_APPLIED);

  assert.equal(verdict, Verdict.NOT_APPLIED);
  assert.equal(idem.store.stateOf("k"), "new", "NOT_APPLIED must release the key");
  assert.notEqual(idem.store.stateOf("k"), "succeeded", "the library invented a success");
});

test("N3 only an APPLIED verdict may produce a succeeded record", () => {
  for (const [verdict, expected] of [
    [Verdict.APPLIED, "succeeded"],
    [Verdict.NOT_APPLIED, "new"],
    [Verdict.INCONCLUSIVE, "unknown"],
  ] as const) {
    const { idem } = build(tempDir());
    const op = new ScriptedOperation([{ event: "error", class: "ReadTimeout", sent: true }]);
    assert.throws(() => idem.run("k", op.run), OutcomeUnknown);

    idem.reconcile("k", () => verdict);
    assert.equal(idem.store.stateOf("k"), expected, `verdict ${verdict} produced the wrong state`);
  }
});
