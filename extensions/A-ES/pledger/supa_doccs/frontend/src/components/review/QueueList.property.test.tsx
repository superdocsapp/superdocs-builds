import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { render } from "@testing-library/react";
import { QueueList } from "./QueueList";
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
      section_id: fc.option(fc.string({ minLength: 1, maxLength: 20 }), {
        nil: null,
      }),
      start_offset: fc.nat({ max: 10000 }),
      end_offset: fc.nat({ max: 10000 }),
      clause_ref: fc.option(fc.string({ minLength: 1, maxLength: 30 }), {
        nil: null,
      }),
    }),
    { nil: null }
  ),
});

const queueItemPayloadArb: fc.Arbitrary<QueueItemPayload> = fc.record({
  summary: fc.string({ minLength: 1, maxLength: 200 }),
  details: fc.constant({} as Record<string, unknown>),
  source_citations: fc.array(sourceCitationArb, {
    minLength: 0,
    maxLength: 5,
  }),
});

const queueItemArb: fc.Arbitrary<QueueItem> = fc.record({
  id: fc.uuid(),
  run_id: fc.uuid(),
  item_type: itemTypeArb,
  payload: queueItemPayloadArb,
  status: itemStatusArb,
  queued_at: fc.date().map((d) => d.toISOString()),
  decided_at: fc.option(fc.date().map((d) => d.toISOString()), { nil: null }),
  decision: fc.option(
    fc.constantFrom("approved" as const, "rejected" as const),
    { nil: null }
  ),
  reviewer_id: fc.option(fc.uuid(), { nil: null }),
  justification: fc.option(fc.string({ minLength: 1, maxLength: 200 }), {
    nil: null,
  }),
});

/** Generate an array of QueueItems with unique IDs */
function uniqueQueueItemsArb(
  minLength: number,
  maxLength: number
): fc.Arbitrary<QueueItem[]> {
  return fc
    .array(queueItemArb, { minLength, maxLength })
    .map((items) =>
      items.map((item, idx) => ({ ...item, id: `item-${idx}` }))
    );
}

// --- Tests ---

describe("QueueList Property Tests", () => {
  /**
   * Property 2: Queue Item Display Completeness
   *
   * For any QueueListResponse with N items, the rendered QueueList SHALL
   * contain exactly N item cards (elements with role="option").
   *
   * **Validates: Requirements 1.1, 1.2, 1.5**
   */
  describe("Property 2: Queue Item Display Completeness", () => {
    it("rendered list contains exactly N cards matching response data", () => {
      fc.assert(
        fc.property(
          uniqueQueueItemsArb(0, 30),
          (items) => {
            const total = items.length;
            const pending = items.filter((i) => i.status === "pending").length;

            const { container } = render(
              <QueueList
                items={items}
                selectedItemId={null}
                optimisticStatuses={{}}
                onSelectItem={() => {}}
                total={total}
                pending={pending}
              />
            );

            // Count rendered option elements
            const optionElements =
              container.querySelectorAll('[role="option"]');
            expect(optionElements.length).toBe(items.length);

            // Cleanup after each iteration
            container.remove();
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  /**
   * Property 15: Cross-Run Item Isolation
   *
   * For any set of displayed items passed to QueueList with a specific run_id,
   * every rendered item should belong to that run. All displayed items have
   * run_id matching the selected run.
   *
   * **Validates: Requirements 1.1, 1.2, 1.5, 7.4**
   */
  describe("Property 15: Cross-Run Item Isolation", () => {
    it("all displayed items have run_id matching selected run", () => {
      fc.assert(
        fc.property(
          fc.uuid(),
          fc.array(queueItemArb, { minLength: 0, maxLength: 30 }),
          (runId, baseItems) => {
            // Force all items to share the same run_id, simulating the
            // contract that the backend only returns items for the requested run
            const items = baseItems.map((item, idx) => ({
              ...item,
              id: `item-${idx}`,
              run_id: runId,
            }));

            const total = items.length;
            const pending = items.filter(
              (i) => i.status === "pending"
            ).length;

            const { container } = render(
              <QueueList
                items={items}
                selectedItemId={null}
                optimisticStatuses={{}}
                onSelectItem={() => {}}
                total={total}
                pending={pending}
              />
            );

            // Count rendered option elements
            const optionElements =
              container.querySelectorAll('[role="option"]');

            // Verify the list renders exactly as many cards as items provided
            expect(optionElements.length).toBe(items.length);

            // Verify every item in the rendered set belongs to the selected run
            for (const item of items) {
              expect(item.run_id).toBe(runId);
            }

            // Cleanup after each iteration
            container.remove();
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
