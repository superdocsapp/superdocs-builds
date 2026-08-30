import { describe, expect, it } from "vitest";
import { diffDocumentHtml } from "../src/chunkDiff";
import { looksLikeCompletedEditClaim, reconcileTurn } from "../src/claimReconciler";
import type { NormalizedTurnEvent } from "../src/types";

function turn(overrides: Partial<NormalizedTurnEvent> = {}): NormalizedTurnEvent {
  return {
    turnId: "s1:1",
    sessionId: "s1",
    turnIndex: 1,
    documentId: "doc1",
    clientType: "unknown",
    claimedIntentText: "Update the API version to v2.",
    claimedResultText: "I've updated the API version to v2.",
    beforeHtml: '<p data-chunk-id="a">API version: v1</p>',
    afterHtml: '<p data-chunk-id="a">API version: v2</p>',
    wasBillable: true,
    opsCharged: 1,
    timestamp: "2026-01-01T00:00:00.000Z",
    correlationId: "job-1",
    ...overrides,
  };
}

describe("looksLikeCompletedEditClaim", () => {
  it("recognizes plain completed-edit phrasing", () => {
    expect(looksLikeCompletedEditClaim("I've updated the authentication section.")).toBe(true);
    expect(looksLikeCompletedEditClaim("Done. Added a new paragraph.")).toBe(true);
  });

  it("does not flag clarifying questions", () => {
    expect(
      looksLikeCompletedEditClaim("Which section did you mean — 3.1 or 3.2?")
    ).toBe(false);
  });

  it("does not flag an honest no-op explanation", () => {
    expect(
      looksLikeCompletedEditClaim("The document already satisfies this — nothing needed changing.")
    ).toBe(false);
  });

  it("does not flag an explicit failure to locate content", () => {
    expect(looksLikeCompletedEditClaim("I couldn't find an authentication section.")).toBe(false);
  });
});

describe("reconcileTurn", () => {
  it("acceptance test 1 — normal successful edit: match verdict, one real Change", () => {
    const t = turn();
    const diff = diffDocumentHtml(t.beforeHtml, t.afterHtml);
    const reconciled = reconcileTurn(t, diff);
    expect(reconciled.verdict).toBe("match");
    expect(reconciled.changes).toHaveLength(1);
    expect(reconciled.changes[0]).toMatchObject({
      operation: "edit",
      chunkId: "a",
      status: "proposed",
      reconciliation: "match",
    });
  });

  it("acceptance test 2 — claimed edit that never happened: flagged, zero fake Changes created", () => {
    const t = turn({
      claimedResultText: "I've updated the authentication section.",
      beforeHtml: '<p data-chunk-id="a">unchanged</p>',
      afterHtml: '<p data-chunk-id="a">unchanged</p>', // AI's edit target didn't exist; nothing moved
      wasBillable: false,
      opsCharged: 0,
    });
    const result = reconcileTurn(t, []); // empty diff: nothing actually changed
    expect(result.verdict).toBe("claimed_not_observed");
    expect(result.changes).toEqual([]); // <- the non-negotiable part: no fake Change
  });

  it("does not flag a legitimate no-op turn (a question) as claimed-not-observed", () => {
    const t = turn({
      claimedIntentText: "Which section talks about liability?",
      claimedResultText: "Section 4 covers liability, in the second paragraph.",
      wasBillable: false,
      opsCharged: 0,
    });
    const result = reconcileTurn(t, []);
    expect(result.verdict).toBe("no_claim");
    expect(result.changes).toEqual([]);
  });

  it("flags a non-empty diff whose turn was not billed as conflicting, not blindly trusted", () => {
    const t = turn({ wasBillable: false, opsCharged: 0 });
    const diff = diffDocumentHtml(t.beforeHtml, t.afterHtml);
    const result = reconcileTurn(t, diff);
    expect(result.verdict).toBe("conflicting");
    expect(result.changes).toHaveLength(1);
    expect(result.changes[0]?.reconciliation).toBe("conflicting");
  });

  it("every Change from one turn shares that turn's verdict and turnId", () => {
    const before = '<h1 data-chunk-id="title">Old</h1><p data-chunk-id="para">Old para</p>';
    const after = '<h1 data-chunk-id="title">New</h1><p data-chunk-id="para">New para</p>';
    const t = turn({ beforeHtml: before, afterHtml: after });
    const result = reconcileTurn(t, diffDocumentHtml(before, after));
    expect(result.changes).toHaveLength(2);
    for (const c of result.changes) {
      expect(c.turnId).toBe(t.turnId);
      expect(c.reconciliation).toBe(result.verdict);
    }
  });
});
