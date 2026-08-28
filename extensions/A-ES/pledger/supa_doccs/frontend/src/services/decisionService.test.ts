import { describe, it, expect, vi, beforeEach } from "vitest";
import { submitItemDecision } from "./decisionService";
import { useQueueStore } from "@/stores/queueStore";
import type { QueueItem } from "@/types/review";

// Mock the approvalApi module
vi.mock("./approvalApi", () => ({
  submitDecision: vi.fn(),
  fetchItem: vi.fn(),
  ApiError: class ApiError extends Error {
    type: string;
    status?: number;
    constructor(message: string, type: string, status?: number) {
      super(message);
      this.name = "ApiError";
      this.type = type;
      this.status = status;
    }
  },
}));

import { submitDecision, fetchItem, ApiError } from "./approvalApi";

const mockSubmitDecision = submitDecision as ReturnType<typeof vi.fn>;
const mockFetchItem = fetchItem as ReturnType<typeof vi.fn>;

function createMockItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "item-1",
    run_id: "run-1",
    item_type: "finding",
    payload: {
      summary: "Test finding",
      details: {},
      source_citations: [],
    },
    status: "pending",
    queued_at: "2024-01-01T00:00:00Z",
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
    ...overrides,
  };
}

describe("submitItemDecision", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useQueueStore.getState().reset();
  });

  it("applies optimistic update before POST request", async () => {
    mockSubmitDecision.mockResolvedValue({
      item_id: "item-1",
      decision: "approved",
      success: true,
      error: null,
    });

    const applyOptimisticSpy = vi.spyOn(
      useQueueStore.getState(),
      "applyOptimisticUpdate"
    );

    await submitItemDecision({
      itemId: "item-1",
      decision: "approved",
      reviewerId: "reviewer-1",
      justification: "Looks good",
    });

    expect(applyOptimisticSpy).toHaveBeenCalledWith("item-1", "approved");
  });

  it("returns success and clears optimistic update on successful POST", async () => {
    mockSubmitDecision.mockResolvedValue({
      item_id: "item-1",
      decision: "approved",
      success: true,
      error: null,
    });

    // Seed the store with an item
    useQueueStore.setState({
      items: [createMockItem()],
      optimisticStatuses: {},
    });

    const result = await submitItemDecision({
      itemId: "item-1",
      decision: "approved",
      reviewerId: "reviewer-1",
      justification: "Approved after review",
    });

    expect(result).toEqual({ success: true });
    // Optimistic status should be cleared
    expect(useQueueStore.getState().optimisticStatuses).not.toHaveProperty(
      "item-1"
    );
  });

  it("rolls back optimistic update on non-409 failure", async () => {
    mockSubmitDecision.mockRejectedValue(new Error("Network request failed"));

    // Seed the store
    useQueueStore.setState({
      items: [createMockItem()],
      optimisticStatuses: {},
    });

    const result = await submitItemDecision({
      itemId: "item-1",
      decision: "rejected",
      reviewerId: "reviewer-1",
      justification: "Not compliant",
    });

    expect(result).toEqual({
      success: false,
      error: "Network request failed",
    });
    // Optimistic status should be cleared (rolled back)
    expect(useQueueStore.getState().optimisticStatuses).not.toHaveProperty(
      "item-1"
    );
  });

  it("handles 409 conflict by refreshing item from server", async () => {
    const conflictError = new ApiError("Resource conflict", "conflict", 409);
    mockSubmitDecision.mockRejectedValue(conflictError);

    const freshItem = createMockItem({
      id: "item-1",
      status: "approved",
      decision: "approved",
      decided_at: "2024-01-01T01:00:00Z",
      reviewer_id: "other-reviewer",
      justification: "Already approved",
    });
    mockFetchItem.mockResolvedValue(freshItem);

    // Seed the store
    useQueueStore.setState({
      items: [createMockItem()],
      optimisticStatuses: {},
    });

    const result = await submitItemDecision({
      itemId: "item-1",
      decision: "approved",
      reviewerId: "reviewer-1",
      justification: "Looks good",
    });

    expect(result).toEqual({
      success: false,
      alreadyDecided: true,
      error: "Item was already decided",
    });
    expect(mockFetchItem).toHaveBeenCalledWith("item-1");
    // Item in store should be updated with fresh data
    const storeItem = useQueueStore
      .getState()
      .items.find((i) => i.id === "item-1");
    expect(storeItem?.status).toBe("approved");
    expect(storeItem?.reviewer_id).toBe("other-reviewer");
  });

  it("rolls back on 409 when fetchItem also fails", async () => {
    const conflictError = new ApiError("Resource conflict", "conflict", 409);
    mockSubmitDecision.mockRejectedValue(conflictError);
    mockFetchItem.mockRejectedValue(new Error("Network failed"));

    // Seed the store
    useQueueStore.setState({
      items: [createMockItem()],
      optimisticStatuses: {},
    });

    const result = await submitItemDecision({
      itemId: "item-1",
      decision: "approved",
      reviewerId: "reviewer-1",
      justification: "Looks good",
    });

    expect(result).toEqual({
      success: false,
      alreadyDecided: true,
      error: "Item was already decided",
    });
    // Should have rolled back since fetchItem failed
    expect(useQueueStore.getState().optimisticStatuses).not.toHaveProperty(
      "item-1"
    );
  });

  it("sends correct payload to submitDecision", async () => {
    mockSubmitDecision.mockResolvedValue({
      item_id: "item-1",
      decision: "rejected",
      success: true,
      error: null,
    });

    await submitItemDecision({
      itemId: "item-1",
      decision: "rejected",
      reviewerId: "reviewer-42",
      justification: "Non-compliant finding",
    });

    expect(mockSubmitDecision).toHaveBeenCalledWith("item-1", {
      decision: "rejected",
      reviewer_id: "reviewer-42",
      justification: "Non-compliant finding",
    });
  });

  it("does not modify other items in the store during decision", async () => {
    mockSubmitDecision.mockResolvedValue({
      item_id: "item-1",
      decision: "approved",
      success: true,
      error: null,
    });

    const otherItem = createMockItem({ id: "item-2", status: "pending" });
    useQueueStore.setState({
      items: [createMockItem(), otherItem],
      optimisticStatuses: {},
    });

    await submitItemDecision({
      itemId: "item-1",
      decision: "approved",
      reviewerId: "reviewer-1",
      justification: "Good",
    });

    // Other item should be completely unchanged
    const otherItemAfter = useQueueStore
      .getState()
      .items.find((i) => i.id === "item-2");
    expect(otherItemAfter).toEqual(otherItem);
  });
});
