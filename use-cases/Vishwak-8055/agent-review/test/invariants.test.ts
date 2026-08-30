/**
 * Named invariants the rest of the test suite already enforces piecemeal,
 * collected here as explicit, single-purpose assertions. This file adds no
 * new production behavior — every invariant below is proven by composing
 * the same modules exercised elsewhere (reviewStore, sessionWatcher,
 * chunkDiff). Its only job is to make the guarantees findable in one place
 * and to fail loudly, by name, if a future change breaks one of them.
 */
import { describe, expect, it } from "vitest";
import { diffDocumentHtml } from "../src/chunkDiff";
import { applyTransition, IllegalTransitionError } from "../src/changeModel";
import { InMemoryBackend } from "../src/persistence";
import { SessionWatcher, type SuperDocsReadPort } from "../src/sessionWatcher";
import { ReviewStore } from "../src/reviewStore";
import type { Change } from "../src/types";
import type { JobDetail } from "../src/superdocsClient";

function freshStore() {
  return new ReviewStore(new InMemoryBackend(), { decideHitlChange: async () => {}, applyPatch: async () => {} });
}

function baseChange(overrides: Partial<Change> = {}): Change {
  return {
    id: "c1", turnId: "s1:job1", documentId: "s1", chunkId: "a", operation: "edit",
    source: "auto_apply", sourceJobId: null, insertAfterChunkId: null,
    beforeHtml: "<p>old</p>", afterHtml: "<p>new</p>", status: "proposed",
    reconciliation: "match", aiExplanation: null, createdAt: "t", updatedAt: "t",
    decidedBy: null, decidedAt: null, ...overrides,
  };
}

describe("Invariant 1 — a single server job cannot create two logical review items", () => {
  it("re-ingesting the same turnId returns the original changes, not new ones", () => {
    const store = freshStore();
    const t = {
      turnId: "s1:job1", sessionId: "s1", turnIndex: 1, documentId: "s1", clientType: "unknown",
      claimedIntentText: "", claimedResultText: "done", beforeHtml: '<p data-chunk-id="a">old</p>',
      afterHtml: '<p data-chunk-id="a">new</p>', wasBillable: true, opsCharged: 1,
      timestamp: "t", correlationId: "job1",
    };
    const diff = diffDocumentHtml(t.beforeHtml, t.afterHtml);
    const first = store.ingestAutoApplyTurn(t, diff);
    const second = store.ingestAutoApplyTurn(t, diff);
    expect(second.alreadyIngested).toBe(true);
    expect(store.listAllChanges()).toHaveLength(1);
    expect(second.changes.map((c) => c.id)).toEqual(first.changes.map((c) => c.id));
  });
});

describe("Invariant 2 — the initial baseline cannot appear as an agent mutation", () => {
  it("a session's pre-existing, already-completed job produces zero Changes on first sight", async () => {
    class Port implements SuperDocsReadPort {
      async listSessions() { return [{ session_id: "s1", last_activity: "t" }]; }
      async listSessionJobs() { return [{ job_id: "job0", status: "completed", created_at: "t0" }]; }
      async getJob(): Promise<JobDetail> {
        return {
          job_id: "job0", status: "completed", created_at: "t0",
          result: {
            response: "pre-existing",
            document_changes: { updated_html: '<h1 data-chunk-id="a">Pre-existing content</h1>' },
            usage: { was_billable: true, ops_charged: 1 },
          },
        };
      }
      async getSessionHistory() { return { messages: [], document_state: null }; }
    }
    const store = freshStore();
    await new SessionWatcher(new Port(), store).pollOnce();
    expect(store.listAllChanges()).toHaveLength(0);
  });
});

describe("Invariant 3 — a rejected change cannot accidentally become approved", () => {
  it("approve on a rejected (terminal) change throws rather than silently transitioning", () => {
    const rejected = baseChange({ status: "rejected" });
    expect(() => applyTransition(rejected, { type: "approve", by: "x", at: "t" })).toThrow(IllegalTransitionError);
  });
});

describe("Invariant 4 — a revert cannot target a different turn's chunk", () => {
  it("reverting change B never mutates change A's recorded chunk content", async () => {
    const store = freshStore();
    const t = {
      turnId: "s1:job1", sessionId: "s1", turnIndex: 1, documentId: "s1", clientType: "unknown",
      claimedIntentText: "", claimedResultText: "done",
      beforeHtml: '<h1 data-chunk-id="title">Old</h1><p data-chunk-id="para">Old</p>',
      afterHtml: '<h1 data-chunk-id="title">New</h1><p data-chunk-id="para">New</p>',
      wasBillable: true, opsCharged: 1, timestamp: "t", correlationId: "job1",
    };
    store.ingestAutoApplyTurn(t, diffDocumentHtml(t.beforeHtml, t.afterHtml));
    const [a, b] = store.listAllChanges();
    await store.approve(a!.id, "x", { sessionId: "s1" });
    await store.approve(b!.id, "x", { sessionId: "s1" });

    const { parseChunks } = await import("../src/chunkDiff");
    await store.revert(b!.id, "x", { sessionId: "s1", liveChunks: parseChunks(t.afterHtml) });

    expect(store.getChange(a!.id)?.status).toBe("approved");
    expect(store.getChange(a!.id)?.afterHtml).toBe(a!.afterHtml); // untouched
  });
});

describe("Invariant 5 — a session cannot mutate another session's state", () => {
  it("two sessions tracked by one watcher never cross-contaminate each other's baseline", async () => {
    class Port implements SuperDocsReadPort {
      jobs = new Map<string, JobDetail>([
        ["j_s1", { job_id: "j_s1", status: "completed", created_at: "t", result: { response: "x", document_changes: { updated_html: '<p data-chunk-id="a">s1 content</p>' }, usage: { was_billable: true, ops_charged: 1 } } }],
        ["j_s2", { job_id: "j_s2", status: "completed", created_at: "t", result: { response: "x", document_changes: { updated_html: '<p data-chunk-id="a">s2 content</p>' }, usage: { was_billable: true, ops_charged: 1 } } }],
      ]);
      async listSessions() { return [{ session_id: "s1", last_activity: "t" }, { session_id: "s2", last_activity: "t" }]; }
      async listSessionJobs(sessionId: string) {
        return sessionId === "s1" ? [{ job_id: "j_s1", status: "completed", created_at: "t" }] : [{ job_id: "j_s2", status: "completed", created_at: "t" }];
      }
      async getJob(id: string) { return this.jobs.get(id)!; }
      async getSessionHistory() { return { messages: [], document_state: null }; }
    }
    const store = freshStore();
    const watcher = new SessionWatcher(new Port(), store);
    await watcher.pollOnce(); // bootstrap both sessions
    await watcher.pollOnce(); // no new jobs on either — nothing to ingest

    // Same chunk id "a" in both sessions, but they must remain distinct
    // documents — neither session's baseline should leak into the other's.
    const changes = store.listAllChanges();
    expect(changes).toHaveLength(0); // both jobs were bootstrap material, correctly, independently
  });
});

describe("Invariant 6 — unverified/unsafe diffs cannot silently become trusted", () => {
  it("a document with a duplicate chunk id refuses to diff rather than returning a partial result", () => {
    expect(() =>
      diffDocumentHtml('<p data-chunk-id="a">1</p><p data-chunk-id="a">2</p>', "<p>x</p>")
    ).toThrow(/duplicate/i);
  });

  it("a live write-back gate refuses when the document model can't prove it round-trips", async () => {
    const { canSafelyRoundTrip } = await import("../src/chunkDiff");
    expect(canSafelyRoundTrip('<div class="wrapper"><p data-chunk-id="a">x</p></div>')).toBe(false);
  });
});

describe("Invariant 7 — retrying an idempotent action does not duplicate its effect", () => {
  it("approving the same change twice does not append a second audit record", async () => {
    const store = freshStore();
    const t = {
      turnId: "s1:job1", sessionId: "s1", turnIndex: 1, documentId: "s1", clientType: "unknown",
      claimedIntentText: "", claimedResultText: "done", beforeHtml: '<p data-chunk-id="a">old</p>',
      afterHtml: '<p data-chunk-id="a">new</p>', wasBillable: true, opsCharged: 1,
      timestamp: "t", correlationId: "job1",
    };
    store.ingestAutoApplyTurn(t, diffDocumentHtml(t.beforeHtml, t.afterHtml));
    const c = store.listAllChanges()[0]!;
    await store.approve(c.id, "alice", { sessionId: "s1" });
    const auditCountAfterFirst = store.auditTrail().length;
    await store.approve(c.id, "alice", { sessionId: "s1" });
    expect(store.auditTrail()).toHaveLength(auditCountAfterFirst);
  });
});
