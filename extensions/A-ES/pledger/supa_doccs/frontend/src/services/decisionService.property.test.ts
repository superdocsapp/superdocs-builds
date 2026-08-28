import { describe, it, expect, beforeEach, vi } from "vitest";
import fc from "fast-check";
import { useQueueStore } from "@/stores/queueStore";
import { submitItemDecision } from "@/services/decisionService";
import type { DecisionResponse } from "@/types/review";

// Mock the approvalApi module
vi.mock("@/services/approvalApi", () => ({
  submitDecision: vi.fn(),
  fetchItem: vi.fn(),
  ApiError: class ApiError extends Error {
    type: string;
    status?: number;
    constructor(
      message: string,
      type: "not_found" | "conflict" | "server_error" | "network_error",
      status?: number
    ) {
      super(message);
      this.name = "ApiError";
      this.type = type;
      this.status = status;
    }
  },
}));

// Import after mock setup so we get the mocked versions
import { submitDecision, ApiError } from "@/services/approvalApi";

const mockedSubmitDecision = vi.mocked(submitDecision);

// --- Arbitraries ---

const decisionArb = fc.constantFrom("approved" as const, "rejected" as const);

const errorTypeArb = fc.constantFrom(
  "not_found" as const,
  "server_error" as const,
  "network_error" as const
);

// --- Tests ---

describe("DecisionService Property Tests", () => {
  beforeEach(() => {
    useQueueStore.getState().reset();
    vi.clearAllMocks();
  });

  /**
   * Property 7: Optimistic Update Immediacy
   *
   * For any decision submission on a pending item, the optimistic status in the
   * store SHALL be set to the submitted decision value BEFORE the network response
   * arrives. The local item status transitions synchronously before the network
   * response is received.
   *
   * **Validates: Requirements 4.1**
   */
  describe("Property 7: Optimistic Update Immediacy", () => {
    it("local status transitions to submitted decision before network response arrives", async () => {
      await fc.assert(
        fc.asyncProperty(
          fc.uuid(),
          decisionArb,
          fc.uuid(),
          fc.string({ minLength: 1, maxLength: 200 }),
          async (itemId, decision, reviewerId, justification) => {
            // Reset store state for each iteration
            useQueueStore.getState().reset();
            vi.clearAllMocks();

            // Mock submitDecision to return a pending promise that we control
            let resolvePromise!: (value: DecisionResponse) => void;
            const pendingPromise = new Promise<DecisionResponse>((resolve) => {
              resolvePromise = resolve;
            });
            mockedSubmitDecision.mockReturnValue(pendingPromise);

            // Call submitItemDecision (don't await — we want to check state mid-flight)
            const resultPromise = submitItemDecision({
              itemId,
              decision,
              reviewerId,
              justification,
            });

            // IMMEDIATELY check that optimistic status is set (before network response)
            const optimisticStatuses =
              useQueueStore.getState().optimisticStatuses;
            expect(optimisticStatuses[itemId]).toBe(decision);

            // Now resolve the promise to allow cleanup
            resolvePromise({
              item_id: itemId,
              decision,
              success: true,
              error: null,
            });

            // Wait for the promise to complete and verify cleanup
            const result = await resultPromise;
            expect(result.success).toBe(true);

            // After success, optimistic status should be cleared
            const afterStatuses =
              useQueueStore.getState().optimisticStatuses;
            expect(afterStatuses[itemId]).toBeUndefined();
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  /**
   * Property 8: Rollback on Decision Failure
   *
   * For any decision submission where the POST request fails (network error or
   * non-2xx other than 409), the optimistic status SHALL be removed (rolled back)
   * and the function returns an error result.
   *
   * **Validates: Requirements 4.2**
   */
  describe("Property 8: Rollback on Decision Failure", () => {
    it("status reverts (optimistic status removed) on POST failure and result indicates error", async () => {
      await fc.assert(
        fc.asyncProperty(
          fc.uuid(),
          decisionArb,
          fc.uuid(),
          fc.string({ minLength: 1, maxLength: 200 }),
          errorTypeArb,
          fc.string({ minLength: 1, maxLength: 100 }),
          async (
            itemId,
            decision,
            reviewerId,
            justification,
            errorType,
            errorMessage
          ) => {
            // Reset store state for each iteration
            useQueueStore.getState().reset();
            vi.clearAllMocks();

            // Mock submitDecision to throw an ApiError with a non-conflict type
            mockedSubmitDecision.mockRejectedValue(
              new ApiError(
                errorMessage,
                errorType,
                errorType === "server_error" ? 500 : undefined
              )
            );

            // Call submitItemDecision and await the result
            const result = await submitItemDecision({
              itemId,
              decision,
              reviewerId,
              justification,
            });

            // Verify rollback: optimistic status should be removed (undefined)
            const optimisticStatuses =
              useQueueStore.getState().optimisticStatuses;
            expect(optimisticStatuses[itemId]).toBeUndefined();

            // Verify the result indicates failure
            expect(result.success).toBe(false);
            expect(result.error).toBeDefined();
            expect(result.alreadyDecided).toBeFalsy();
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
