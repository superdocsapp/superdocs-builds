import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { applyFilters, applySorting } from "./filterSort";
import { itemIsUnverifiable } from "./citationHelpers";
import type {
  QueueItem,
  QueueFilters,
  ItemType,
  SortField,
  SourceCitation,
} from "@/types/review";

// --- Generators ---

const itemTypeArb: fc.Arbitrary<ItemType> = fc.constantFrom(
  "finding",
  "conflict",
  "proposed_update"
);

const citationStatusArb = fc.constantFrom("grounded" as const, "unverifiable" as const);

const sourceCitationArb: fc.Arbitrary<SourceCitation> = fc.record({
  claim_id: fc.uuid(),
  claim_text: fc.string({ minLength: 1, maxLength: 50 }),
  citation_status: citationStatusArb,
  source_location: fc.constant(null),
});

const queueItemArb: fc.Arbitrary<QueueItem> = fc.record({
  id: fc.uuid(),
  run_id: fc.uuid(),
  item_type: itemTypeArb,
  payload: fc.record({
    summary: fc.string({ minLength: 1, maxLength: 100 }),
    details: fc.constant({}),
    source_citations: fc.array(sourceCitationArb, { minLength: 0, maxLength: 5 }),
  }),
  status: fc.constantFrom("pending" as const, "approved" as const, "rejected" as const),
  queued_at: fc.date({ min: new Date("2020-01-01"), max: new Date("2030-01-01") }).map(
    (d) => d.toISOString()
  ),
  decided_at: fc.constant(null),
  decision: fc.constant(null),
  reviewer_id: fc.constant(null),
  justification: fc.constant(null),
});

const queueItemsArb = fc.array(queueItemArb, { minLength: 0, maxLength: 30 });

const queueFiltersArb: fc.Arbitrary<QueueFilters> = fc.record({
  itemType: fc.oneof(fc.constant(null), itemTypeArb),
  unverifiableOnly: fc.boolean(),
});

const sortFieldArb: fc.Arbitrary<SortField> = fc.constantFrom("item_type", "queued_at");
const sortDirectionArb: fc.Arbitrary<"asc" | "desc"> = fc.constantFrom("asc", "desc");

// --- Helper predicates (use the single shared unverifiable definition) ---

function matchesFilter(item: QueueItem, filters: QueueFilters): boolean {
  if (filters.itemType !== null && item.item_type !== filters.itemType) {
    return false;
  }
  if (filters.unverifiableOnly && !itemIsUnverifiable(item.payload.source_citations)) {
    return false;
  }
  return true;
}

// --- Property Tests ---

/**
 * **Validates: Requirements 2.1, 2.2**
 */
describe("Property 3: Filter Correctness", () => {
  it("filtered result contains exactly matching items and no others", () => {
    fc.assert(
      fc.property(queueItemsArb, queueFiltersArb, (items, filters) => {
        const result = applyFilters(items, filters);

        // Every item in the result must match the filter
        for (const item of result) {
          expect(matchesFilter(item, filters)).toBe(true);
        }

        // Every item from the original that matches the filter must appear in the result
        const expectedMatching = items.filter((item) => matchesFilter(item, filters));
        expect(result.length).toBe(expectedMatching.length);

        // No item that does NOT match should appear in the result
        const resultIds = new Set(result.map((item) => item.id));
        for (const item of items) {
          if (!matchesFilter(item, filters)) {
            expect(resultIds.has(item.id)).toBe(false);
          }
        }
      }),
      { numRuns: 100 }
    );
  });

  it("result length equals count of matching items in the original", () => {
    fc.assert(
      fc.property(queueItemsArb, queueFiltersArb, (items, filters) => {
        const result = applyFilters(items, filters);
        const expectedCount = items.filter((item) => matchesFilter(item, filters)).length;
        expect(result.length).toBe(expectedCount);
      }),
      { numRuns: 100 }
    );
  });
});

/**
 * **Validates: Requirements 2.3**
 */
describe("Property 4: Sort Correctness", () => {
  it("result is ordered according to criterion and direction", () => {
    fc.assert(
      fc.property(
        queueItemsArb,
        sortFieldArb,
        sortDirectionArb,
        (items, sortBy, direction) => {
          const result = applySorting(items, sortBy, direction);

          // For every pair of adjacent items, the comparison should be consistent
          for (let i = 0; i < result.length - 1; i++) {
            const a = result[i];
            const b = result[i + 1];

            let comparison: number;
            if (sortBy === "item_type") {
              comparison = a.item_type.localeCompare(b.item_type);
            } else {
              comparison = a.queued_at.localeCompare(b.queued_at);
            }

            if (direction === "asc") {
              expect(comparison).toBeLessThanOrEqual(0);
            } else {
              expect(comparison).toBeGreaterThanOrEqual(0);
            }
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it("sorting does not add or remove items (length preserved)", () => {
    fc.assert(
      fc.property(
        queueItemsArb,
        sortFieldArb,
        sortDirectionArb,
        (items, sortBy, direction) => {
          const result = applySorting(items, sortBy, direction);
          expect(result.length).toBe(items.length);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("every item from the input appears in the output", () => {
    fc.assert(
      fc.property(
        queueItemsArb,
        sortFieldArb,
        sortDirectionArb,
        (items, sortBy, direction) => {
          const result = applySorting(items, sortBy, direction);
          const resultIds = result.map((item) => item.id).sort();
          const inputIds = items.map((item) => item.id).sort();
          expect(resultIds).toEqual(inputIds);
        }
      ),
      { numRuns: 100 }
    );
  });
});
