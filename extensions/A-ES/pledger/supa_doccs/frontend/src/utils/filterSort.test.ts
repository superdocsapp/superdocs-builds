import { describe, it, expect } from "vitest";
import { applyFilters, applySorting } from "./filterSort";
import type { QueueItem, QueueFilters } from "@/types/review";

function makeItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "item-1",
    run_id: "run-1",
    item_type: "finding",
    payload: {
      summary: "Test summary",
      details: {},
      source_citations: [],
    },
    status: "pending",
    queued_at: "2024-01-15T10:00:00Z",
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
    ...overrides,
  };
}

describe("applyFilters", () => {
  const items: QueueItem[] = [
    makeItem({ id: "1", item_type: "finding" }),
    makeItem({ id: "2", item_type: "conflict" }),
    makeItem({ id: "3", item_type: "proposed_update" }),
    makeItem({
      id: "4",
      item_type: "finding",
      payload: {
        summary: "Has unverifiable",
        details: {},
        source_citations: [
          {
            claim_id: "c1",
            claim_text: "claim",
            citation_status: "unverifiable",
            source_location: null,
          },
        ],
      },
    }),
    makeItem({
      id: "5",
      item_type: "conflict",
      payload: {
        summary: "Has grounded",
        details: {},
        source_citations: [
          {
            claim_id: "c2",
            claim_text: "claim",
            citation_status: "grounded",
            source_location: {
              page_number: 1,
              section_id: null,
              start_offset: 0,
              end_offset: 10,
              clause_ref: "3.1",
            },
          },
        ],
      },
    }),
  ];

  it("returns all items when no filters are active", () => {
    const filters: QueueFilters = { itemType: null, unverifiableOnly: false };
    const result = applyFilters(items, filters);
    expect(result).toHaveLength(5);
  });

  it("filters by item_type", () => {
    const filters: QueueFilters = { itemType: "finding", unverifiableOnly: false };
    const result = applyFilters(items, filters);
    expect(result).toHaveLength(2);
    expect(result.every((item) => item.item_type === "finding")).toBe(true);
  });

  it("filters by unverifiableOnly", () => {
    const filters: QueueFilters = { itemType: null, unverifiableOnly: true };
    const result = applyFilters(items, filters);
    // Items 1-3 have empty citations arrays (unverifiable by definition),
    // item 4 has an explicitly unverifiable citation. Item 5 is grounded.
    expect(result).toHaveLength(4);
    expect(result.map((i) => i.id).sort()).toEqual(["1", "2", "3", "4"]);
  });

  it("treats an empty citations array as unverifiable (regression: run eef332ea)", () => {
    const filters: QueueFilters = { itemType: null, unverifiableOnly: true };
    const result = applyFilters(items, filters);
    expect(result.map((i) => i.id)).toContain("1");
  });

  it("combines item_type and unverifiableOnly filters (AND logic)", () => {
    const filters: QueueFilters = { itemType: "finding", unverifiableOnly: true };
    const result = applyFilters(items, filters);
    expect(result).toHaveLength(2);
    expect(result.map((i) => i.id).sort()).toEqual(["1", "4"]);
  });

  it("returns only empty-citation conflicts when combined filters match", () => {
    const filters: QueueFilters = { itemType: "conflict", unverifiableOnly: true };
    const result = applyFilters(items, filters);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("2");
  });

  it("does not mutate the input array", () => {
    const filters: QueueFilters = { itemType: "finding", unverifiableOnly: false };
    const original = [...items];
    applyFilters(items, filters);
    expect(items).toEqual(original);
  });
});

describe("applySorting", () => {
  const items: QueueItem[] = [
    makeItem({ id: "1", item_type: "proposed_update", queued_at: "2024-01-15T12:00:00Z" }),
    makeItem({ id: "2", item_type: "conflict", queued_at: "2024-01-15T08:00:00Z" }),
    makeItem({ id: "3", item_type: "finding", queued_at: "2024-01-15T10:00:00Z" }),
  ];

  it("sorts by item_type ascending (alphabetical A-Z)", () => {
    const result = applySorting(items, "item_type", "asc");
    expect(result.map((i) => i.item_type)).toEqual([
      "conflict",
      "finding",
      "proposed_update",
    ]);
  });

  it("sorts by item_type descending (alphabetical Z-A)", () => {
    const result = applySorting(items, "item_type", "desc");
    expect(result.map((i) => i.item_type)).toEqual([
      "proposed_update",
      "finding",
      "conflict",
    ]);
  });

  it("sorts by queued_at ascending (earliest first)", () => {
    const result = applySorting(items, "queued_at", "asc");
    expect(result.map((i) => i.id)).toEqual(["2", "3", "1"]);
  });

  it("sorts by queued_at descending (latest first)", () => {
    const result = applySorting(items, "queued_at", "desc");
    expect(result.map((i) => i.id)).toEqual(["1", "3", "2"]);
  });

  it("does not mutate the input array", () => {
    const original = [...items];
    applySorting(items, "item_type", "asc");
    expect(items).toEqual(original);
  });

  it("handles empty arrays", () => {
    const result = applySorting([], "item_type", "asc");
    expect(result).toEqual([]);
  });

  it("handles single-element arrays", () => {
    const single = [makeItem({ id: "only" })];
    const result = applySorting(single, "queued_at", "desc");
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("only");
  });
});
