import { submitDecision, fetchItem, ApiError } from "./approvalApi";
import { useQueueStore } from "@/stores/queueStore";

export interface DecisionRequest {
  itemId: string;
  decision: "approved" | "rejected";
  reviewerId: string;
  justification: string;
}

export interface DecisionResult {
  success: boolean;
  error?: string;
  alreadyDecided?: boolean;
}

/**
 * Submits an item decision with the 5-step optimistic update lifecycle:
 *
 * 1. Apply optimistic update → UI updates immediately
 * 2. POST to /approval/items/{item_id}/decide
 * 3. On success → clear optimistic update (server data matches on next poll)
 * 4. On failure → rollback optimistic update, return error
 * 5. On 409 → refresh item from server, clear optimistic, return alreadyDecided
 */
export async function submitItemDecision(
  req: DecisionRequest
): Promise<DecisionResult> {
  const store = useQueueStore.getState();

  // Step 1: Apply optimistic update — UI reflects the decision immediately
  store.applyOptimisticUpdate(req.itemId, req.decision);

  try {
    // Step 2: POST decision to server
    await submitDecision(req.itemId, {
      decision: req.decision,
      reviewer_id: req.reviewerId,
      justification: req.justification,
    });

    // Step 3: On success, clear optimistic update (server now matches)
    useQueueStore.getState().clearOptimisticUpdate(req.itemId);
    return { success: true };
  } catch (error) {
    if (error instanceof ApiError && error.type === "conflict") {
      // Step 5: On 409, refresh item from server
      try {
        const freshItem = await fetchItem(req.itemId);
        // Update the item in the store with fresh server data
        const currentState = useQueueStore.getState();
        const updatedItems = currentState.items.map((item) =>
          item.id === req.itemId ? freshItem : item
        );
        useQueueStore.setState({ items: updatedItems });
        useQueueStore.getState().clearOptimisticUpdate(req.itemId);
      } catch {
        // If refresh also fails, rollback to pending
        useQueueStore.getState().rollbackOptimisticUpdate(req.itemId);
      }
      return {
        success: false,
        alreadyDecided: true,
        error: "Item was already decided",
      };
    }

    // Step 4: On failure, rollback optimistic update (status reverts to pending)
    useQueueStore.getState().rollbackOptimisticUpdate(req.itemId);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}
