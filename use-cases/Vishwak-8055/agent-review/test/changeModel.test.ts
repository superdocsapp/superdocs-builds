import { describe, expect, it } from "vitest";
import { applyTransition, IllegalTransitionError, isTerminal } from "../src/changeModel";
import type { Change } from "../src/types";

function baseChange(overrides: Partial<Change> = {}): Change {
  return {
    id: "c1",
    turnId: "s1:1",
    documentId: "doc1",
    chunkId: "a",
    operation: "edit",
    source: "auto_apply",
    sourceJobId: null,
    insertAfterChunkId: null,
    beforeHtml: "<p>old</p>",
    afterHtml: "<p>new</p>",
    status: "proposed",
    reconciliation: "match",
    aiExplanation: null,
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
    decidedBy: null,
    decidedAt: null,
    ...overrides,
  };
}

describe("applyTransition — legal paths", () => {
  it("acceptance test 4 — reject: proposed -> rejected, never becomes committed", () => {
    const proposed = baseChange();
    const rejected = applyTransition(proposed, { type: "reject", by: "alice", at: "t1" });
    expect(rejected.status).toBe("rejected");
    expect(rejected.decidedBy).toBe("alice");
    expect(isTerminal(rejected.status)).toBe(true);
  });

  it("proposed -> approved -> reverted", () => {
    const proposed = baseChange();
    const approved = applyTransition(proposed, { type: "approve", by: "alice", at: "t1" });
    expect(approved.status).toBe("approved");
    const reverted = applyTransition(approved, { type: "revert", by: "alice", at: "t2" });
    expect(reverted.status).toBe("reverted");
    expect(isTerminal(reverted.status)).toBe(true);
  });

  it("conflicted changes can be resolved to approved or rejected", () => {
    const conflicted = baseChange({ status: "conflicted" });
    const approved = applyTransition(conflicted, {
      type: "resolveConflict",
      resolution: "approved",
      by: "alice",
      at: "t1",
    });
    expect(approved.status).toBe("approved");
  });
});

describe("applyTransition — double-submit is a safe no-op, not an error", () => {
  it("approving an already-approved change returns it unchanged", () => {
    const approved = baseChange({ status: "approved", decidedBy: "alice", decidedAt: "t1" });
    const result = applyTransition(approved, { type: "approve", by: "bob", at: "t2" });
    expect(result).toEqual(approved); // still alice/t1 — second submit did not overwrite
  });

  it("rejecting an already-rejected change returns it unchanged", () => {
    const rejected = baseChange({ status: "rejected", decidedBy: "alice", decidedAt: "t1" });
    const result = applyTransition(rejected, { type: "reject", by: "bob", at: "t2" });
    expect(result).toEqual(rejected);
  });

  it("reverting an already-reverted change returns it unchanged", () => {
    const reverted = baseChange({ status: "reverted", decidedBy: "alice", decidedAt: "t1" });
    const result = applyTransition(reverted, { type: "revert", by: "bob", at: "t2" });
    expect(result).toEqual(reverted);
  });
});

describe("applyTransition — illegal paths throw rather than silently corrupt state", () => {
  it("cannot revert a change that was never approved", () => {
    const proposed = baseChange();
    expect(() => applyTransition(proposed, { type: "revert", by: "alice", at: "t1" })).toThrow(
      IllegalTransitionError
    );
  });

  it("cannot approve a rejected (terminal) change", () => {
    const rejected = baseChange({ status: "rejected" });
    expect(() => applyTransition(rejected, { type: "approve", by: "alice", at: "t1" })).toThrow(
      IllegalTransitionError
    );
  });

  it("cannot revert a reverted change's sibling logic by resolving a non-conflicted change", () => {
    const approved = baseChange({ status: "approved" });
    expect(() =>
      applyTransition(approved, { type: "resolveConflict", resolution: "approved", by: "a", at: "t" })
    ).toThrow(IllegalTransitionError);
  });

  it("cannot supersede a change that has already been decided", () => {
    const approved = baseChange({ status: "approved" });
    expect(() => applyTransition(approved, { type: "supersede", at: "t1" })).toThrow(
      IllegalTransitionError
    );
  });
});
