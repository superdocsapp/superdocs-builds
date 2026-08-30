import { describe, expect, it } from "vitest";
import { diffDocumentHtml, parseChunks } from "../src/chunkDiff";
import { applyRevertPatch, planRevert } from "../src/revertEngine";
import type { Change } from "../src/types";

function changeFromDiffEntry(entry: ReturnType<typeof diffDocumentHtml>[number]): Change {
  return {
    id: `c-${entry.chunkId}`,
    turnId: "s1:1",
    documentId: "doc1",
    chunkId: entry.chunkId,
    operation: entry.operation,
    source: "auto_apply",
    sourceJobId: null,
    beforeHtml: entry.beforeHtml,
    afterHtml: entry.afterHtml,
    insertAfterChunkId: entry.insertAfterChunkId,
    status: "approved",
    reconciliation: "match",
    aiExplanation: null,
    createdAt: "t0",
    updatedAt: "t0",
    decidedBy: "alice",
    decidedAt: "t0",
  };
}

describe("planRevert — acceptance test 3: independent revert", () => {
  it("reverting change B leaves change A's chunk untouched", () => {
    // Turn 1: title (A) and paragraph (B) both edited.
    const before =
      '<h1 data-chunk-id="title">Old Title</h1><p data-chunk-id="para">Old paragraph.</p>';
    const after =
      '<h1 data-chunk-id="title">New Title</h1><p data-chunk-id="para">New paragraph.</p>';
    const diff = diffDocumentHtml(before, after);
    const changeA = changeFromDiffEntry(diff.find((d) => d.chunkId === "title")!);
    const changeB = changeFromDiffEntry(diff.find((d) => d.chunkId === "para")!);

    // Both approved; live document reflects both.
    let live = parseChunks(after);

    const plan = planRevert(changeB, live);
    expect(plan.safe).toBe(true);
    if (!plan.safe) throw new Error("expected safe plan");
    live = applyRevertPatch(live, plan.patch);

    // B reverted...
    expect(live.get("para")).toBe('<p data-chunk-id="para">Old paragraph.</p>');
    // ...but A is untouched.
    expect(live.get("title")).toBe('<h1 data-chunk-id="title">New Title</h1>');

    // And re-planning a revert of A afterward still works cleanly — proof
    // that reverting B didn't leave A in some inconsistent intermediate state.
    const planA = planRevert(changeA, live);
    expect(planA.safe).toBe(true);
  });

  it("does not overwrite a chunk a later change has since modified", () => {
    const before = '<p data-chunk-id="a">v1</p>';
    const afterFirstEdit = '<p data-chunk-id="a">v2</p>';
    const diff1 = diffDocumentHtml(before, afterFirstEdit);
    const change1 = changeFromDiffEntry(diff1[0]!);

    // A second, later change further edits the same chunk before change1 is reverted.
    const liveAfterSecondEdit = parseChunks('<p data-chunk-id="a">v3 (from a later change)</p>');

    const plan = planRevert(change1, liveAfterSecondEdit);
    expect(plan.safe).toBe(false);
    if (plan.safe) throw new Error("expected an unsafe/conflict plan");
    expect(plan.reason).toMatch(/changed since/);
    expect(plan.liveHtml).toBe('<p data-chunk-id="a">v3 (from a later change)</p>');
  });

  it("flags a conflict rather than silently no-op-ing when the chunk was deleted since approval", () => {
    const before = '<p data-chunk-id="a">v1</p>';
    const after = '<p data-chunk-id="a">v2</p>';
    const change = changeFromDiffEntry(diffDocumentHtml(before, after)[0]!);
    const liveAfterDeletion = new Map<string, string>(); // chunk gone
    const plan = planRevert(change, liveAfterDeletion);
    expect(plan.safe).toBe(false);
  });

  it("reverting a create removes exactly that chunk", () => {
    const before = '<p data-chunk-id="a">A</p>';
    const after = '<p data-chunk-id="a">A</p><p data-chunk-id="b">B (new)</p>';
    const change = changeFromDiffEntry(
      diffDocumentHtml(before, after).find((d) => d.operation === "create")!
    );
    const live = parseChunks(after);
    const plan = planRevert(change, live);
    expect(plan.safe).toBe(true);
    if (!plan.safe) throw new Error("expected safe plan");
    const result = applyRevertPatch(live, plan.patch);
    expect(result.has("b")).toBe(false);
    expect(result.get("a")).toBe('<p data-chunk-id="a">A</p>');
  });

  it("reverting a delete re-inserts the chunk at its original position", () => {
    const before =
      '<p data-chunk-id="a">A</p><p data-chunk-id="b">B</p><p data-chunk-id="c">C</p>';
    const after = '<p data-chunk-id="a">A</p><p data-chunk-id="c">C</p>';
    const change = changeFromDiffEntry(
      diffDocumentHtml(before, after).find((d) => d.operation === "delete")!
    );
    const live = parseChunks(after);
    const plan = planRevert(change, live);
    expect(plan.safe).toBe(true);
    if (!plan.safe) throw new Error("expected safe plan");
    const result = applyRevertPatch(live, plan.patch);
    expect([...result.keys()]).toEqual(["a", "b", "c"]); // restored between a and c
    expect(result.get("b")).toBe('<p data-chunk-id="b">B</p>');
  });
});
