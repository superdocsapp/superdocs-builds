/**
 * Runs vectors.json — the same file the Python implementation runs.
 *
 * If these two suites ever disagree, the specification is ambiguous and SPEC.md
 * is what gets fixed, not whichever implementation is more convenient.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { OutcomeUnknown, RetriesExhausted, TerminalFailure } from "../src/index.ts";
import {
  ScriptedOperation,
  build,
  loadPolicy,
  loadVectors,
  probeReturning,
  tempDir,
} from "./harness.ts";

const RAISES: Record<string, any> = { OutcomeUnknown, TerminalFailure, RetriesExhausted };
const VECTORS = loadVectors();

for (const vector of VECTORS) {
  test(vector.id, () => {
    const policy = loadPolicy();
    const { idem, delaysMs } = build(tempDir(), policy);
    const operation = new ScriptedOperation(vector.attempts);
    const probe = probeReturning(vector);
    const key = vector.id;

    for (const [n, invocation] of vector.invocations.entries()) {
      const expect = invocation.expect;
      const call = () =>
        idem.run(key, operation.run, {
          onUnknown: invocation.on_unknown ?? "refuse",
          probe,
          naturallyIdempotent: invocation.naturally_idempotent ?? false,
        });

      if (expect.raised) {
        assert.throws(call, RAISES[expect.raised], `invocation ${n} raised the wrong error`);
      } else {
        assert.deepEqual(call(), expect.result ?? null, `invocation ${n} returned the wrong result`);
      }
    }

    const final = vector.expect;

    // The assertion that matters: how many times the operation actually ran.
    assert.equal(operation.executions, final.executions, "wrong number of executions");
    assert.equal(idem.store.stateOf(key), final.final_state);
    assert.equal(delaysMs.length, final.delay_count, `delays were ${delaysMs}`);

    if (final.delays_exact_ms) {
      assert.deepEqual(delaysMs, final.delays_exact_ms);
    }

    if (final.assert_delay_bounds) {
      // By bound, never by value: seeded RNGs are not portable across
      // languages, so pinning exact delays would pin an implementation detail
      // rather than the specified behaviour (SPEC.md R11).
      delaysMs.forEach((delay, n) => {
        const ceiling = policy.backoff.ceilingMs(n);
        assert.ok(delay >= 0 && delay <= ceiling, `delay ${n} = ${delay}ms exceeds ${ceiling}ms`);
      });
    }
  });
}

test("every vector names a requirement and says why it exists", () => {
  for (const vector of VECTORS) {
    assert.match(vector.requirement ?? "", /^R\d+$/, vector.id);
    assert.ok(vector.why, `${vector.id} does not say why it exists`);
  }
});

test("no vector scripts an attempt the run never reaches", () => {
  for (const vector of VECTORS) {
    assert.equal(
      vector.attempts.length,
      vector.expect.executions,
      `${vector.id}: scripts ${vector.attempts.length} attempts but expects ` +
        `${vector.expect.executions} executions`,
    );
  }
});
