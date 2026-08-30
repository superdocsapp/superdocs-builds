import { describe, expect, it } from "vitest";
import { runSearch } from "../../domain/search";
import { ironcladMsa } from "../../data/documents/ironcladMsa";
import { meridianVsq } from "../../data/documents/meridianVsq";
import { heliosNda } from "../../data/documents/heliosNda";

describe("runSearch", () => {
  it("returns nothing for an empty query", () => {
    expect(runSearch([ironcladMsa], "")).toEqual({ matchedCommand: null, results: [] });
    expect(runSearch([ironcladMsa], "   ")).toEqual({ matchedCommand: null, results: [] });
  });

  it('runs the "Find unsupported claims" command and returns exactly the unsupported claims', () => {
    const { matchedCommand, results } = runSearch([ironcladMsa], "unsupported claims");
    expect(matchedCommand?.id).toBe("unsupported-claims");
    expect(results).toHaveLength(4);
    expect(results.every((r) => r.kind === "Claim")).toBe(true);
  });

  it('matches a partial keyword like "high risk" to the high-risk-documents command', () => {
    const { matchedCommand, results } = runSearch([ironcladMsa, meridianVsq, heliosNda], "high risk");
    expect(matchedCommand?.id).toBe("high-risk-documents");
    const ids = results.map((r) => r.documentId);
    expect(ids).toContain(ironcladMsa.id);
    expect(ids).toContain(meridianVsq.id);
    expect(ids).not.toContain(heliosNda.id);
    // Critical (Meridian, score 21) should outrank High (Ironclad, score 20).
    expect(results[0]?.documentId).toBe(meridianVsq.id);
  });

  it("finds stale evidence across documents via the stale-evidence command", () => {
    const { matchedCommand, results } = runSearch([ironcladMsa], "stale evidence");
    expect(matchedCommand?.id).toBe("stale-evidence");
    expect(results.map((r) => r.id).sort()).toEqual(["ev-ic-05", "ev-ic-06"]);
  });

  it("falls back to free-text search across titles, claims, and evidence when no command matches", () => {
    const byTitle = runSearch([ironcladMsa], "ironclad");
    expect(byTitle.matchedCommand).toBeNull();
    expect(byTitle.results.some((r) => r.kind === "Document" && r.documentId === ironcladMsa.id)).toBe(true);

    const byClaimText = runSearch([ironcladMsa], "uptime");
    expect(byClaimText.results.some((r) => r.kind === "Claim" && r.id === "claim-ic-01")).toBe(true);
  });

  it("finds documents awaiting approval", () => {
    const { results } = runSearch([ironcladMsa, heliosNda], "awaiting approval");
    expect(results).toHaveLength(1);
    expect(results[0]?.documentId).toBe(ironcladMsa.id);
  });
});
