import { describe, it, expect, beforeEach } from "vitest";
import fc from "fast-check";
import { useQueueStore } from "./queueStore";
import type {
  QueueItem,
  QueueItemPayload,
  SourceCitation,
  ItemType,
  ItemStatus,
} from "@/types/review";

// --- Arbitraries ---

const itemTypeArb: fc.Arbitrary<ItemType> = fc.constantFrom(
  "finding",
  "conflict",
  "proposed_update"
);

const itemStatusArb: fc.Arbitrary<ItemStatus> = fc.constantFrom(
  "pending",
  "approved",
  "rejected"
);

const sourceCitationArb: fc.Arbitrary<SourceCitation> = fc.record({
  claim_id: fc.uuid(),
  claim_text: fc.string({ minLength: 1, maxLength: 100 }),
  citation_status: fc.constantFrom("grounded" as const, "unverifiable" as const),
  source_location: fc.option(
    fc.record({
      page_number: fc.option(fc.integer({ min: 1, max: 500 }), { nil: null }),
      section_id: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
      start_offset: fc.nat({ max: 10000 }),
      end_offset: fc.nat({ max: 10000 }),
      clause_ref: fc.option(fc.string({ minLength: 1, maxLength: 30 }), { nil: null }),
    }),
    { nil: null }
  ),
});

const queueItemPayloadArb: fc.Arbitrary<QueueItemPayload> = fc.record({
  summary: fc.string({ minLength: 1, maxLength: 200 }),
  details: fc.constant({} as Record<string, unknown>),
  source_citations: fc.array(sourceCitationArb, { minLength: 0, maxLength: 5 }),
});

const queueItemArb: fc.Arbitrary<QueueItem> = fc.record({
  id: fc.uuid(),
  run_id: fc.uuid(),
  item_type: itemTypeArb,
  payload: queueItemPayloadArb,
  status: itemStatusArb,
  queued_at: fc.date().map((d) => d.toISOString()),
  decided_at: fc.option(fc.date().map((d) => d.toISOString()), { nil: null }),
  decision: fc.option(fc.constantFrom("approved" as const, "rejected" as const), {
    nil: null,
  }),
  reviewer_id: fc.option(fc.uuid(), { nil: null }),
  justification: fc.option(fc.string({ minLength: 1, maxLength: 200 }), { nil: null }),
});

// --- Test Setup ---

describe("QueueStore Property Tests", () => {
  beforeEach(() => {
    useQueueStore.getState().reset();
  });

  /**
   * Property 9: Decision Isolation
   *
   * For any queue of N items and any decision on item X, after applying an
   * optimistic update to item X, all other items Y (Y≠X) should remain exactly
   * as they were (status, payload, metadata unchanged).
   *
   * **Validates: Requirements 5.1, 5.2**
   */
  describe("Property 9: Decision Isolation", () => {
    it("applying an optimistic update to item X leaves all other items unchanged", () => {
      fc.assert(
        fc.property(
          fc.uuid(),
          fc
            .array(queueItemArb, { minLength: 2, maxLength: 20 })
            .map((items) =>
              items.map((item, idx) => ({ ...item, id: `item-${idx}` }))
            ),
          fc.nat(),
          fc.constantFrom("approved" as const, "rejected" as const),
          (runId, items, targetIdx, decision) => {
            const boundedIdx = targetIdx % items.length;
            const targetItem = items[boundedIdx];

            // Set up store with items
            const store = useQueueStore;
            store.getState().reset();
            store.getState().setRunId(runId);
            store.getState().mergeItems(items, items.length, items.length);

            // Snapshot all items before the decision
            const itemsBefore = store.getState().items.map((item) => ({
              ...item,
            }));

            // Apply optimistic update to the target item
            store.getState().applyOptimisticUpdate(targetItem.id, decision);

            // Verify all other items are unchanged
            const itemsAfter = store.getState().items;
            for (let i = 0; i < itemsAfter.length; i++) {
              if (i !== boundedIdx) {
                expect(itemsAfter[i]).toEqual(itemsBefore[i]);
              }
            }

            // Also verify the optimistic status map only contains the target
            const optimistic = store.getState().optimisticStatuses;
            expect(optimistic[targetItem.id]).toBe(decision);

            // Verify no other items got optimistic overrides from this action
            const otherItemIds = items
              .filter((_, idx) => idx !== boundedIdx)
              .map((item) => item.id);
            for (const otherId of otherItemIds) {
              expect(optimistic[otherId]).toBeUndefined();
            }
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  /**
   * Property 11: Run Switch Clears State
   *
   * For any current state with items from run A, calling setRunId(runB) results
   * in an empty items array, null selectedItemId, and empty optimisticStatuses.
   *
   * **Validates: Requirements 7.2, 7.4**
   */
  describe("Property 11: Run Switch Clears State", () => {
    it("switching runs clears all items, selection, and optimistic statuses", () => {
      fc.assert(
        fc.property(
          fc.uuid(),
          fc.uuid(),
          fc
            .array(queueItemArb, { minLength: 1, maxLength: 20 })
            .map((items) =>
              items.map((item, idx) => ({ ...item, id: `item-${idx}` }))
            ),
          fc.nat(),
          (runA, runB, items, selectIdx) => {
            const store = useQueueStore;
            store.getState().reset();

            // Set up state with run A data
            store.getState().setRunId(runA);
            store.getState().mergeItems(items, items.length, items.length);

            // Select an item
            const selectedIdx = selectIdx % items.length;
            store.getState().selectItem(items[selectedIdx].id);

            // Apply some optimistic statuses
            if (items.length > 0) {
              store.getState().applyOptimisticUpdate(items[0].id, "approved");
            }

            // Verify state is populated before switch
            expect(store.getState().items.length).toBeGreaterThan(0);

            // Switch to run B
            store.getState().setRunId(runB);

            // Verify state is cleared
            const state = store.getState();
            expect(state.items).toEqual([]);
            expect(state.selectedItemId).toBeNull();
            expect(state.optimisticStatuses).toEqual({});
            expect(state.total).toBe(0);
            expect(state.pending).toBe(0);
            expect(state.runId).toBe(runB);
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  /**
   * Property 12: Polling Merge Preserves Selection
   *
   * For any queue state where selectedItemId is set to an existing item,
   * calling mergeItems with new data (that still contains the selected item)
   * preserves the selectedItemId value.
   *
   * **Validates: Requirements 8.3**
   */
  describe("Property 12: Polling Merge Preserves Selection", () => {
    it("merging new poll data preserves selectedItemId when item still exists", () => {
      fc.assert(
        fc.property(
          fc.uuid(),
          fc
            .array(queueItemArb, { minLength: 2, maxLength: 20 })
            .map((items) =>
              items.map((item, idx) => ({ ...item, id: `item-${idx}` }))
            ),
          fc.nat(),
          (runId, items, selectIdx) => {
            const store = useQueueStore;
            store.getState().reset();

            // Set up initial state
            store.getState().setRunId(runId);
            store.getState().mergeItems(items, items.length, items.length);

            // Select an item
            const selectedIdx = selectIdx % items.length;
            const selectedId = items[selectedIdx].id;
            store.getState().selectItem(selectedId);

            expect(store.getState().selectedItemId).toBe(selectedId);

            // Simulate a poll merge with updated data that still contains the selected item
            // Modify some items slightly (e.g., change status) but keep the selected item present
            const updatedItems = items.map((item) => ({
              ...item,
              // Simulate potential server-side changes
              pending: item.status === "pending" ? 1 : 0,
            }));

            store
              .getState()
              .mergeItems(
                updatedItems as unknown as QueueItem[],
                updatedItems.length,
                updatedItems.length
              );

            // Selection must be preserved
            expect(store.getState().selectedItemId).toBe(selectedId);
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
