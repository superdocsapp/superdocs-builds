/**
 * The fault-injection harness.
 *
 * Three scenarios, the three the task card names: network partition, duplicated
 * request, and process restart. Every one asserts the same thing, because there
 * is only one thing worth asserting — the server applied the edit exactly once.
 *
 * The fake server counts its own applies, so these tests measure what actually
 * happened on the far side rather than what the library believes happened.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import { writeFileSync } from "node:fs";
import { join } from "node:path";

import { Idempotent, OutcomeUnknown, Policy, TerminalFailure, UnknownPolicy, Verdict } from "../src/index.ts";
import { FakeServer, POLICY_PATH, ROOT, build, loadPolicy, tempDir } from "./harness.ts";

const TS_DIR = join(ROOT, "typescript");
const NODE_ARGS = ["--experimental-strip-types", "--no-warnings"];

function serverIn(dir: string) {
  return new FakeServer(join(dir, "server.log"));
}

function probeFor(server: FakeServer) {
  return (record: any) => {
    const job = server.findByOperationKey(record.key);
    return job ? ([Verdict.APPLIED, job] as [Verdict, unknown]) : Verdict.NOT_APPLIED;
  };
}

// ---- 1. network partition ---------------------------------------------------

test("partition: refuses rather than double-applying", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  const { idem } = build(dir);

  assert.throws(
    () => idem.run("edit-1", () => server.chatAsync("edit-1", { loseResponse: true })),
    OutcomeUnknown,
  );
  assert.equal(server.applies, 1);

  for (let i = 0; i < 5; i++) {
    assert.throws(() => idem.run("edit-1", () => server.chatAsync("edit-1")), OutcomeUnknown);
  }

  assert.equal(server.applies, 1, "the operation was applied more than once");
  assert.equal(idem.store.stateOf("edit-1"), "unknown");
});

test("partition: resolves when the server can answer", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  const { idem } = build(dir);

  const result: any = idem.run(
    "edit-2",
    () => server.chatAsync("edit-2", { loseResponse: true }),
    { onUnknown: UnknownPolicy.RECONCILE, probe: probeFor(server) },
  );

  assert.equal(result.status, "completed");
  assert.equal(server.applies, 1);
  assert.equal(idem.store.stateOf("edit-2"), "succeeded");
});

test("partition: stays refused when the server cannot answer", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  const { idem } = build(dir);

  assert.throws(
    () =>
      idem.run("edit-3", () => server.chatAsync("edit-3", { loseResponse: true }), {
        onUnknown: UnknownPolicy.RECONCILE,
      }),
    /inconclusive/,
  );

  assert.equal(server.applies, 1);
  assert.equal(idem.reconcile("edit-3"), Verdict.INCONCLUSIVE);
});

test("partition: a conflict afterwards is not retried", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  const { idem, delaysMs } = build(dir);

  assert.throws(
    () => idem.run("edit-4", () => server.chatAsync("edit-4", { loseResponse: true })),
    OutcomeUnknown,
  );
  assert.throws(
    () => idem.run("edit-5", () => server.chatAsync("edit-5", { conflict: true })),
    TerminalFailure,
  );

  assert.equal(server.applies, 1);
  assert.deepEqual(delaysMs, [], "the library backed off and retried a wedged session");
  assert.equal(idem.store.stateOf("edit-5"), "failed");
});

// ---- 2. duplicated request --------------------------------------------------

test("duplicate: ten sequential submissions apply once", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  const { idem } = build(dir);

  const results = Array.from({ length: 10 }, () =>
    idem.run("edit-6", () => server.chatAsync("edit-6")),
  );

  assert.equal(server.applies, 1);
  for (const r of results) assert.deepEqual(r, results[0]);
});

test("duplicate: two handles on one database apply once", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  const policy = loadPolicy();
  const a = new Idempotent(join(dir, "idem.db"), policy);
  const b = new Idempotent(join(dir, "idem.db"), policy);

  const first = a.run("edit-8", () => server.chatAsync("edit-8"));
  const second = b.run("edit-8", () => {
    throw new Error("the second handle re-executed");
  });

  assert.deepEqual(first, second);
  assert.equal(server.applies, 1);
});

test("duplicate: twelve processes racing across sixty keys apply each once", async () => {
  const dir = tempDir();
  const server = serverIn(dir);

  // Separate processes rather than threads: this exercises the cross-process
  // claim through SQLite's own locking, which is the harder case and the one
  // two workers on a box actually hit (SPEC.md R5, N6).
  // Every child spins on this file, so all twelve hit the claim together.
  const gate = join(dir, "go");

  const children = Array.from({ length: 12 }, () =>
    new Promise<{ code: number; stderr: string }>((resolve) => {
      const child = spawn(
        process.execPath,
        [...NODE_ARGS, "tests/concurrent-child.ts",
         join(dir, "idem.db"), join(dir, "server.log"), "edit-7", POLICY_PATH, gate],
        { cwd: TS_DIR, stdio: ["ignore", "ignore", "pipe"] },
      );
      let stderr = "";
      child.stderr.on("data", (chunk) => (stderr += chunk));
      child.on("exit", (code) => resolve({ code: code ?? -1, stderr }));
    }),
  );

  // Let every child reach the barrier, then release them at once.
  await new Promise((r) => setTimeout(r, 600));
  writeFileSync(gate, "go");

  const results = await Promise.all(children);
  const codes = results.map((r) => r.code);
  const failures = results.filter((r) => r.code !== 0 && r.code !== 3);

  // Sixty keys, twelve processes each. Every key must be applied exactly once:
  // never twice (a double-apply) and never zero (a lost operation).
  const KEYS = 60;
  const perKey = Array.from({ length: KEYS }, (_, n) =>
    server.appliesFor(`edit-7-${n}`),
  );
  const doubled = perKey.filter((c) => c > 1).length;
  const missing = perKey.filter((c) => c === 0).length;

  assert.equal(doubled, 0, `${doubled} of ${KEYS} keys were applied more than once`);
  assert.equal(missing, 0, `${missing} of ${KEYS} keys were never applied`);
  assert.equal(server.applies, KEYS, "total applies should equal the number of keys");
  assert.equal(
    failures.length,
    0,
    `exit codes ${codes}; first failure said:\n${failures[0]?.stderr}`,
  );
  assert.ok(codes.includes(0), "every caller lost the race, which cannot happen");
});

// ---- 3. process restart -----------------------------------------------------

function killMidFlight(dir: string, key: string) {
  const proc = spawnSync(
    process.execPath,
    [...NODE_ARGS, "tests/restart-child.ts",
     join(dir, "idem.db"), join(dir, "server.log"), key, POLICY_PATH],
    { cwd: TS_DIR, encoding: "utf8" },
  );
  assert.equal(proc.signal, "SIGKILL", `child did not die as arranged: ${proc.stderr}`);
}

test("restart: a new process does not quietly redo the work", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  killMidFlight(dir, "edit-9");
  assert.equal(server.applies, 1, "the child did not apply the edit");

  const { idem } = build(dir);
  assert.equal(idem.store.get("edit-9")!.state, "in_flight");

  assert.throws(() => idem.run("edit-9", () => server.chatAsync("edit-9")), OutcomeUnknown);

  assert.equal(server.applies, 1, "the restart double-applied the edit");
  assert.equal(idem.store.stateOf("edit-9"), "unknown");
});

test("restart: reconciling recovers without repeating the work", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  killMidFlight(dir, "edit-10");

  const { idem } = build(dir);
  const result: any = idem.run("edit-10", () => server.chatAsync("edit-10"), {
    onUnknown: UnknownPolicy.RECONCILE,
    probe: probeFor(server),
  });

  assert.equal(result.status, "completed");
  assert.equal(server.applies, 1, "reconciliation re-applied the edit");
  assert.equal(idem.store.stateOf("edit-10"), "succeeded");
});

test("restart: an operation that never reached the server is retried exactly once", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  const { idem } = build(dir);

  // The mirror case: a claim with no attempt behind it, owned by a pid that is
  // not this process.
  idem.store.claim("edit-11");
  new DatabaseSync(join(dir, "idem.db"))
    .prepare("UPDATE operations SET owner_pid = 999999 WHERE key = ?")
    .run("edit-11");

  const result: any = idem.run("edit-11", () => server.chatAsync("edit-11"), {
    onUnknown: UnknownPolicy.RECONCILE,
    probe: probeFor(server),
  });

  assert.equal(result.status, "completed");
  assert.equal(server.applies, 1);
});

// ---- 4. the Review surface: an approval that never settles -------------------
//
// The scenario that cost the most time in production, reproduced as a test.
// `approve_changes(job_id, true)` returned success, the post-approval poll never
// reached terminal, and the next call on that session 409'd — unable to proceed,
// unable to roll back. Approving twice is as wrong as editing twice, so the
// assertion here is `approvals === 1`.

function settleProbeFor(server: FakeServer, jobId: string) {
  return () => {
    const status = server.jobStatus(jobId);
    return ["completed", "failed", "cancelled"].includes(status)
      ? ([Verdict.APPLIED, { job_id: jobId, status }] as [Verdict, unknown])
      : Verdict.INCONCLUSIVE;
  };
}

test("review: an approval whose response is lost is not re-approved", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  const { idem } = build(dir);
  const jobId = "job-review-1";

  assert.throws(
    () => idem.run("approve-1", () => server.approve("approve-1", jobId, { loseResponse: true })),
    OutcomeUnknown,
  );
  assert.equal(server.approvals, 1);

  for (let i = 0; i < 5; i++) {
    assert.throws(
      () => idem.run("approve-1", () => server.approve("approve-1", jobId)),
      OutcomeUnknown,
    );
  }
  assert.equal(server.approvals, 1, "the approval was submitted more than once");
});

test("review: an approval that never settles stays refused", () => {
  // A settle-shaped probe must answer INCONCLUSIVE here, not APPLIED: the
  // approval was accepted, but the operation the caller cares about — the job
  // reaching a terminal state — has not happened.
  const dir = tempDir();
  const server = serverIn(dir);
  const { idem } = build(dir);
  const jobId = "job-review-2";
  const probe = settleProbeFor(server, jobId);

  assert.throws(
    () =>
      idem.run("approve-2",
        () => server.approve("approve-2", jobId, { loseResponse: true, settles: false }),
        { onUnknown: UnknownPolicy.RECONCILE, probe }),
    /inconclusive/,
  );

  assert.equal(server.jobStatus(jobId), "awaiting_approval");
  assert.equal(server.approvals, 1);
  assert.equal(idem.store.stateOf("approve-2"), "unknown");

  for (let i = 0; i < 3; i++) {
    assert.throws(
      () => idem.run("approve-2", () => server.approve("approve-2", jobId),
        { onUnknown: UnknownPolicy.RECONCILE, probe }),
      OutcomeUnknown,
    );
  }
  assert.equal(server.approvals, 1);
});

test("review: an approval that settles late reconciles without re-approving", () => {
  const dir = tempDir();
  const server = serverIn(dir);
  const { idem } = build(dir);
  const jobId = "job-review-3";
  const probe = settleProbeFor(server, jobId);

  assert.throws(
    () =>
      idem.run("approve-3",
        () => server.approve("approve-3", jobId, { loseResponse: true, settles: false }),
        { onUnknown: UnknownPolicy.RECONCILE, probe }),
    OutcomeUnknown,
  );
  assert.equal(idem.reconcile("approve-3", probe), Verdict.INCONCLUSIVE);

  // The server settles the job on its own time — here by a later approval
  // arriving from elsewhere, which is how it looked in production.
  server.approve("out-of-band", jobId, { settles: true });
  const before = server.approvals;

  const result: any = idem.run("approve-3", () => {
    throw new Error("re-approved after settling");
  }, { onUnknown: UnknownPolicy.RECONCILE, probe });

  assert.equal(result.status, "completed");
  assert.equal(idem.store.stateOf("approve-3"), "succeeded");
  assert.equal(server.approvals, before, "reconciliation re-approved");
});

test("review: a denied proposal is recorded once", () => {
  // Denying is as state-changing as approving — a denial that gets replayed can
  // leave the job open, which is the wedge reached from the deny path.
  const dir = tempDir();
  const server = serverIn(dir);
  const { idem } = build(dir);

  idem.run("deny-1", () => server.approve("deny-1", "job-review-4", { settles: true }));
  for (let i = 0; i < 5; i++) {
    idem.run("deny-1", () => {
      throw new Error("the denial was submitted twice");
    });
  }

  assert.equal(server.approvals, 1);
});
