import { beforeEach, describe, expect, it } from "vitest";
import { diffDocumentHtml, parseChunks } from "../src/chunkDiff";
import { IllegalTransitionError } from "../src/changeModel";
import { InMemoryBackend } from "../src/persistence";
import { ReviewStore, type SuperDocsSideEffects } from "../src/reviewStore";
import type { RevertPatch } from "../src/revertEngine";
import type { NormalizedTurnEvent } from "../src/types";

class FakeSideEffects implements SuperDocsSideEffects {
  hitlDecisions: { sessionId: string; jobId: string; changeId: string; approved: boolean; feedback?: string }[] = [];
  patches: { sessionId: string; documentId: string; patch: RevertPatch }[] = [];

  async decideHitlChange(args: {
    sessionId: string;
    jobId: string;
    changeId: string;
    approved: boolean;
    feedback?: string;
  }): Promise<void> {
    this.hitlDecisions.push(args);
  }

  async applyPatch(args: { sessionId: string; documentId: string; patch: RevertPatch }): Promise<void> {
    this.patches.push(args);
  }
}

function turn(overrides: Partial<NormalizedTurnEvent> = {}): NormalizedTurnEvent {
  return {
    turnId: "s1:1",
    sessionId: "s1",
    turnIndex: 1,
    documentId: "doc1",
    clientType: "unknown",
    claimedIntentText: "Update the title and paragraph.",
    claimedResultText: "I've updated the title and paragraph.",
    beforeHtml: '<h1 data-chunk-id="title">Old Title</h1><p data-chunk-id="para">Old para.</p>',
    afterHtml: '<h1 data-chunk-id="title">New Title</h1><p data-chunk-id="para">New para.</p>',
    wasBillable: true,
    opsCharged: 1,
    timestamp: "2026-01-01T00:00:00.000Z",
    correlationId: "job-1",
    ...overrides,
  };
}

describe("ReviewStore.ingestAutoApplyTurn", () => {
  let store: ReviewStore;
  let fx: FakeSideEffects;

  beforeEach(() => {
    fx = new FakeSideEffects();
    store = new ReviewStore(new InMemoryBackend(), fx);
  });

  it("acceptance test 1 — creates one Change per diffed chunk, all proposed/auto_apply", () => {
    const t = turn();
    const result = store.ingestAutoApplyTurn(t, diffDocumentHtml(t.beforeHtml, t.afterHtml));
    expect(result.verdict).toBe("match");
    expect(result.changes).toHaveLength(2);
    expect(result.changes.every((c) => c.status === "proposed" && c.source === "auto_apply")).toBe(true);
  });

  it("acceptance test 9 — duplicate event produces one logical change, not two", () => {
    const t = turn();
    const diff = diffDocumentHtml(t.beforeHtml, t.afterHtml);
    const first = store.ingestAutoApplyTurn(t, diff);
    const second = store.ingestAutoApplyTurn(t, diff); // same turnId sent again

    expect(first.alreadyIngested).toBe(false);
    expect(second.alreadyIngested).toBe(true);
    expect(store.listAllChanges()).toHaveLength(2); // not 4
  });

  it("acceptance test 2 — claimed-not-observed produces zero Changes but one audit entry", () => {
    const t = turn({
      claimedResultText: "I've updated the authentication section.",
      beforeHtml: '<p data-chunk-id="a">unchanged</p>',
      afterHtml: '<p data-chunk-id="a">unchanged</p>',
      wasBillable: false,
      opsCharged: 0,
    });
    const result = store.ingestAutoApplyTurn(t, []);
    expect(result.verdict).toBe("claimed_not_observed");
    expect(result.changes).toEqual([]);
    expect(store.listAllChanges()).toEqual([]);

    const audit = store.auditTrail();
    expect(audit).toHaveLength(1);
    expect(audit[0]).toMatchObject({ turnId: t.turnId, decision: null });
    expect(audit[0]?.claim).toContain("authentication section");
  });

  it("supersedes an earlier still-pending change on the same chunk", () => {
    const turn1 = turn({ turnId: "s1:1" });
    store.ingestAutoApplyTurn(turn1, diffDocumentHtml(turn1.beforeHtml, turn1.afterHtml));
    const titleChangeId = store.listAllChanges().find((c) => c.chunkId === "title")!.id;

    // A second turn edits the title chunk again before anyone decided on the first proposal.
    const turn2 = turn({
      turnId: "s1:2",
      turnIndex: 2,
      beforeHtml: turn1.afterHtml,
      afterHtml: '<h1 data-chunk-id="title">Newer Title</h1><p data-chunk-id="para">New para.</p>',
    });
    store.ingestAutoApplyTurn(turn2, diffDocumentHtml(turn2.beforeHtml, turn2.afterHtml));

    expect(store.getChange(titleChangeId)?.status).toBe("superseded");
  });
});

describe("ReviewStore — approve / reject / revert (auto_apply)", () => {
  let store: ReviewStore;
  let fx: FakeSideEffects;
  let t: NormalizedTurnEvent;

  beforeEach(() => {
    fx = new FakeSideEffects();
    store = new ReviewStore(new InMemoryBackend(), fx);
    t = turn();
    store.ingestAutoApplyTurn(t, diffDocumentHtml(t.beforeHtml, t.afterHtml));
  });

  it("approve is a pure sign-off — no side effect call, since the change is already live", async () => {
    const titleChange = store.listAllChanges().find((c) => c.chunkId === "title")!;
    const { change } = await store.approve(titleChange.id, "alice", { sessionId: "s1" });
    expect(change.status).toBe("approved");
    expect(fx.patches).toEqual([]);
    expect(fx.hitlDecisions).toEqual([]);
  });

  it("approving twice does not duplicate audit entries or re-run side effects", async () => {
    const c = store.listAllChanges()[0]!;
    await store.approve(c.id, "alice", { sessionId: "s1" });
    const auditCountAfterFirst = store.auditTrail().length;
    await store.approve(c.id, "bob", { sessionId: "s1" }); // second submit
    expect(store.auditTrail()).toHaveLength(auditCountAfterFirst); // no new entry
    expect(store.getChange(c.id)?.decidedBy).toBe("alice"); // bob's second submit did not overwrite
  });

  it("reject undoes an already-applied auto_apply change via a chunk-scoped patch", async () => {
    const titleChange = store.listAllChanges().find((c) => c.chunkId === "title")!;
    const liveChunks = parseChunks(t.afterHtml);
    const { change } = await store.reject(titleChange.id, "alice", { sessionId: "s1", liveChunks }, "not needed");
    expect(change.status).toBe("rejected");
    expect(fx.patches).toHaveLength(1);
    expect(fx.patches[0]?.patch).toMatchObject({ kind: "restore", chunkId: "title" });
  });

  it("reject reports a conflict instead of overwriting when the chunk changed since", async () => {
    const titleChange = store.listAllChanges().find((c) => c.chunkId === "title")!;
    const liveChunksMovedOn = parseChunks('<h1 data-chunk-id="title">Someone else changed this</h1>');
    const { change, conflict } = await store.reject(titleChange.id, "alice", {
      sessionId: "s1",
      liveChunks: liveChunksMovedOn,
    });
    expect(change.status).toBe("conflicted");
    expect(conflict).toBeDefined();
    expect(fx.patches).toEqual([]); // never applied a patch against unknown content
  });

  it("acceptance test 3 — reverting one approved change leaves the sibling change from the same turn untouched", async () => {
    const titleChange = store.listAllChanges().find((c) => c.chunkId === "title")!;
    const paraChange = store.listAllChanges().find((c) => c.chunkId === "para")!;

    await store.approve(titleChange.id, "alice", { sessionId: "s1" });
    await store.approve(paraChange.id, "alice", { sessionId: "s1" });

    let liveChunks = parseChunks(t.afterHtml);
    const { change: revertedPara } = await store.revert(paraChange.id, "alice", { sessionId: "s1", liveChunks });
    expect(revertedPara.status).toBe("reverted");

    // Apply the recorded patch to a local mirror of "the live document" the
    // way the session watcher would, so we can assert on the resulting state.
    liveChunks = applyFakePatch(liveChunks, fx.patches[0]!.patch);
    expect(liveChunks.get("para")).toBe('<p data-chunk-id="para">Old para.</p>');
    expect(liveChunks.get("title")).toBe('<h1 data-chunk-id="title">New Title</h1>'); // untouched

    expect(store.getChange(titleChange.id)?.status).toBe("approved"); // never touched
  });

  it("revert throws for a change that was never approved", async () => {
    const c = store.listAllChanges()[0]!;
    await expect(store.revert(c.id, "alice", { sessionId: "s1", liveChunks: parseChunks(t.afterHtml) })).rejects.toBeInstanceOf(
      IllegalTransitionError
    );
  });

  it("acceptance test 4 — reject leaves rejection in audit history without a committed mutation being kept", async () => {
    const c = store.listAllChanges()[0]!;
    const { change } = await store.reject(c.id, "alice", { sessionId: "s1", liveChunks: parseChunks(t.afterHtml) });
    expect(change.status).toBe("rejected");
    const auditForChange = store.auditTrail().filter((a) => a.changeId === c.id);
    expect(auditForChange.some((a) => a.decision === "rejected")).toBe(true);
  });
});

describe("ReviewStore — HITL-sourced changes", () => {
  it("approve reads the originating jobId from the change itself and calls SuperDocs's approve endpoint", async () => {
    const fx = new FakeSideEffects();
    const store = new ReviewStore(new InMemoryBackend(), fx);
    const t = turn({ correlationId: "job_1" });
    const [change] = store.ingestHitlPendingChanges(t, [
      {
        changeId: "ch_1",
        chunkId: "title",
        operation: "edit",
        oldHtml: '<h1 data-chunk-id="title">Old Title</h1>',
        newHtml: '<h1 data-chunk-id="title">New Title</h1>',
        explanation: "Updated the title per your request.",
        insertAfterChunkId: null,
      },
    ]);
    expect(change!.sourceJobId).toBe("job_1"); // captured automatically at ingestion

    const { change: approved } = await store.approve(change!.id, "alice", { sessionId: "s1" });
    expect(approved.status).toBe("approved");
    expect(fx.hitlDecisions).toEqual([{ sessionId: "s1", jobId: "job_1", changeId: change!.id, approved: true }]);
  });

  it("refuses to approve a HITL change with no recorded sourceJobId rather than silently skipping the SuperDocs call", async () => {
    const fx = new FakeSideEffects();
    const backend = new InMemoryBackend();
    const store = new ReviewStore(backend, fx);
    // Simulate data corruption / a hand-constructed record bypassing normal
    // ingestion — the only realistic way this field would ever be missing.
    backend.set("change:broken", {
      id: "broken",
      turnId: "s1:1",
      documentId: "doc1",
      chunkId: "a",
      operation: "edit",
      source: "hitl",
      sourceJobId: null,
      insertAfterChunkId: null,
      beforeHtml: "<p>old</p>",
      afterHtml: "<p>new</p>",
      status: "proposed",
      reconciliation: "match",
      aiExplanation: "x",
      createdAt: "t",
      updatedAt: "t",
      decidedBy: null,
      decidedAt: null,
    });
    await expect(store.approve("broken", "alice", { sessionId: "s1" })).rejects.toThrow(/sourceJobId/);
  });

  it("reject denies without ever touching the document (nothing was applied yet)", async () => {
    const fx = new FakeSideEffects();
    const store = new ReviewStore(new InMemoryBackend(), fx);
    const t = turn({ correlationId: "job_1" });
    const [change] = store.ingestHitlPendingChanges(t, [
      {
        changeId: "ch_1",
        chunkId: "title",
        operation: "edit",
        oldHtml: "<h1>Old</h1>",
        newHtml: "<h1>New</h1>",
        explanation: "Updated the title.",
        insertAfterChunkId: null,
      },
    ]);

    const { change: rejected } = await store.reject(change!.id, "alice", { sessionId: "s1" }, "no thanks");
    expect(rejected.status).toBe("rejected");
    expect(fx.patches).toEqual([]); // never applied — HITL means it was never live
    expect(fx.hitlDecisions[0]).toMatchObject({ approved: false, feedback: "no thanks" });
  });
});

describe("ReviewStore.resolveConflict", () => {
  it("lets a human resolve a conflicted change to approved or rejected", async () => {
    const fx = new FakeSideEffects();
    const store = new ReviewStore(new InMemoryBackend(), fx);
    const t = turn();
    store.ingestAutoApplyTurn(t, diffDocumentHtml(t.beforeHtml, t.afterHtml));
    const c = store.listAllChanges()[0]!;
    await store.approve(c.id, "alice", { sessionId: "s1" });

    const movedOn = parseChunks('<h1 data-chunk-id="title">Moved on</h1><p data-chunk-id="para">Moved on</p>');
    const { change: conflicted } = await store.revert(c.id, "alice", { sessionId: "s1", liveChunks: movedOn });
    expect(conflicted.status).toBe("conflicted");

    const resolved = store.resolveConflict(c.id, "approved", "alice");
    expect(resolved.status).toBe("approved");
  });
});

/** Test-only helper mirroring what a real caller does with a returned RevertPatch. */
function applyFakePatch(chunks: Map<string, string>, patch: RevertPatch): Map<string, string> {
  const next = new Map(chunks);
  if (patch.kind === "restore") next.set(patch.chunkId, patch.html);
  if (patch.kind === "remove") next.delete(patch.chunkId);
  if (patch.kind === "reinsert") next.set(patch.chunkId, patch.html);
  return next;
}
