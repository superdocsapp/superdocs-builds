import { describe, expect, it } from "vitest";
import { computeAttentionItems, computeDashboardMetrics } from "../../domain/attention";
import { ironcladMsa } from "../../data/documents/ironcladMsa";
import { SEED_DOCUMENTS } from "../../data/documents";

describe("computeAttentionItems", () => {
  it("surfaces the flagship document's open High risks, stale evidence, failed requirements, and pending approval", () => {
    const items = computeAttentionItems([ironcladMsa]);
    const ids = items.map((i) => i.id);

    expect(ids).toEqual(expect.arrayContaining(["risk-ic-01", "risk-ic-02", "risk-ic-05", "risk-ic-08"]));
    expect(ids).toEqual(expect.arrayContaining(["ev-ic-05", "ev-ic-06"]));
    expect(ids).toEqual(expect.arrayContaining(["req-ic-03", "req-ic-10", "req-ic-14"]));
    expect(items.some((i) => i.kind === "Pending Approval")).toBe(true);
    expect(items.some((i) => i.kind === "High-Impact Change")).toBe(true);
  });

  it("sorts items by severity, most severe first", () => {
    const items = computeAttentionItems(SEED_DOCUMENTS);
    const severityRank: Record<string, number> = { Critical: 3, High: 2, Medium: 1, Low: 0 };
    for (let i = 1; i < items.length; i += 1) {
      expect(severityRank[items[i - 1]!.severity]).toBeGreaterThanOrEqual(severityRank[items[i]!.severity]);
    }
  });

  it("produces no items for a fully clean document", () => {
    const helios = SEED_DOCUMENTS.find((d) => d.id === "doc-helios-nda")!;
    expect(computeAttentionItems([helios])).toEqual([]);
  });
});

describe("computeDashboardMetrics", () => {
  it("aggregates counts across the whole workspace", () => {
    const metrics = computeDashboardMetrics(SEED_DOCUMENTS);
    expect(metrics.totalDocuments).toBe(SEED_DOCUMENTS.length);
    expect(metrics.totalClaims).toBe(SEED_DOCUMENTS.reduce((sum, d) => sum + d.claims.length, 0));
    expect(metrics.documentsAtHighOrCriticalRisk).toBe(2); // Ironclad (High) and Meridian (Critical)
    expect(metrics.pendingReviews).toBe(2); // Ironclad and Meridian are both "In Review"
  });
});
