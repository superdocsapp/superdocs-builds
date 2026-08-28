import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fc from "fast-check";
import { renderHook, act } from "@testing-library/react";
import { usePolling } from "./usePolling";
import { useQueueStore } from "@/stores/queueStore";
import { useRunProgressStore } from "@/stores/runProgressStore";
import type {
  QueueItem,
  QueueItemPayload,
  SourceCitation,
  ItemType,
  ItemStatus,
  QueueListResponse,
  PipelineProgress,
} from "@/types/review";

// --- Mock the API module ---
vi.mock("@/services/approvalApi", () => ({
  fetchQueue: vi.fn(),
  fetchRunProgress: vi.fn(),
}));

import { fetchQueue, fetchRunProgress } from "@/services/approvalApi";

const mockFetchQueue = vi.mocked(fetchQueue);
const mockFetchRunProgress = vi.mocked(fetchRunProgress);

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
  claim_text: fc.string({ minLength: 1, maxLength: 50 }),
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
  summary: fc.string({ minLength: 1, maxLength: 100 }),
  details: fc.constant({} as Record<string, unknown>),
  source_citations: fc.array(sourceCitationArb, { minLength: 0, maxLength: 3 }),
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
  justification: fc.option(fc.string({ minLength: 1, maxLength: 100 }), { nil: null }),
});

/** Generate an array of QueueItems with unique IDs sharing a single run_id */
function uniqueQueueItemsForRunArb(
  runId: string,
  minLength: number,
  maxLength: number
): fc.Arbitrary<QueueItem[]> {
  return fc
    .array(queueItemArb, { minLength, maxLength })
    .map((items) =>
      items.map((item, idx) => ({
        ...item,
        id: `item-${idx}`,
        run_id: runId,
      }))
    );
}

// --- Tests ---

describe("usePolling Property Tests", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useQueueStore.getState().reset();
    useRunProgressStore.getState().reset();
    mockFetchQueue.mockReset();
    mockFetchRunProgress.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  /**
   * Property 13: Network Error Preserves Local State
   *
   * For any network error during a polling fetch, the local queue state
   * (items, selection, optimistic updates) SHALL remain unchanged, and a
   * connection-lost indicator SHALL be displayed.
   *
   * **Validates: Requirements 11.3**
   */
  describe("Property 13: Network Error Preserves Local State", () => {
    it("local queue state is unchanged on network error and connectionLost is true", async () => {
      const runId = "test-run-id";

      await fc.assert(
        fc.asyncProperty(
          uniqueQueueItemsForRunArb(runId, 1, 15),
          fc.option(fc.integer({ min: 0, max: 14 }), { nil: null }),
          fc.record({
            current_node: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
            completed_nodes: fc.array(fc.string({ minLength: 1, maxLength: 20 }), { minLength: 0, maxLength: 5 }),
            node_status: fc.option(
              fc.constantFrom("completed" as const, "skipped" as const, "error" as const),
              { nil: null }
            ),
            run_status: fc.constantFrom("running" as const, "completed" as const, "failed" as const, "paused" as const),
          }),
          async (items, selectedIdx, progress) => {
            // Reset stores before each iteration
            useQueueStore.getState().reset();
            useRunProgressStore.getState().reset();

            const total = items.length;
            const pending = items.filter((i) => i.status === "pending").length;

            // Initial successful fetch response
            const queueResponse: QueueListResponse = {
              run_id: runId,
              items,
              total,
              pending,
            };
            const progressResponse: PipelineProgress = progress;

            // First call succeeds (populate state), second call throws
            mockFetchQueue
              .mockResolvedValueOnce(queueResponse)
              .mockRejectedValueOnce(new Error("Network failure"));
            mockFetchRunProgress
              .mockResolvedValueOnce(progressResponse)
              .mockRejectedValueOnce(new Error("Network failure"));

            const { result, unmount } = renderHook(() =>
              usePolling({ intervalMs: 10000, enabled: true, runId })
            );

            // Wait for initial fetch to complete
            await act(async () => {
              await vi.advanceTimersByTimeAsync(0);
            });

            // Verify initial state was populated
            expect(useQueueStore.getState().items).toEqual(items);

            // Set up selection if provided
            if (selectedIdx !== null && selectedIdx < items.length) {
              act(() => {
                useQueueStore.getState().selectItem(items[selectedIdx].id);
              });
            }

            // Capture local state before the error
            const stateBeforeError = {
              items: [...useQueueStore.getState().items],
              selectedItemId: useQueueStore.getState().selectedItemId,
              optimisticStatuses: { ...useQueueStore.getState().optimisticStatuses },
              total: useQueueStore.getState().total,
              pending: useQueueStore.getState().pending,
            };

            // Advance timer to trigger the next poll (which will fail)
            await act(async () => {
              await vi.advanceTimersByTimeAsync(10000);
            });

            // Verify: connectionLost is true
            expect(result.current.connectionLost).toBe(true);

            // Verify: local queue state is unchanged
            const stateAfterError = useQueueStore.getState();
            expect(stateAfterError.items).toEqual(stateBeforeError.items);
            expect(stateAfterError.selectedItemId).toBe(stateBeforeError.selectedItemId);
            expect(stateAfterError.optimisticStatuses).toEqual(stateBeforeError.optimisticStatuses);
            expect(stateAfterError.total).toBe(stateBeforeError.total);
            expect(stateAfterError.pending).toBe(stateBeforeError.pending);

            unmount();
          }
        ),
        { numRuns: 100 }
      );
    }, 60000);
  });
});
