import { describe, it, expect, beforeEach } from "vitest";
import { useQueueStore } from "./queueStore";
import type { QueueItem } from "@/types/review";

function makeItem(overrides: Partial<QueueItem> = {}): QueueItem {
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

describe("queueStore", () => {
  beforeEach(() => {
    useQueueStore.getState().reset();
  });

  describe("setRunId", () => {
    it("sets runId and clears items and selection", () => {
      const store = useQueueStore.getState();
      // Set up some state first
      store.mergeItems([makeItem()], 1, 1);
      store.selectItem("item-1");

      // Switch run
      useQueueStore.getState().setRunId("run-2");

      const state = useQueueStore.getState();
      expect(state.runId).toBe("run-2");
      expect(state.items).toEqual([]);
      expect(state.total).toBe(0);
      expect(state.pending).toBe(0);
      expect(state.selectedItemId).toBeNull();
      expect(state.optimisticStatuses).toEqual({});
    });
  });

  describe("mergeItems", () => {
    it("replaces items with fresh data", () => {
      const store = useQueueStore.getState();
      store.mergeItems([makeItem({ id: "a" })], 1, 1);

      useQueueStore
        .getState()
        .mergeItems([makeItem({ id: "b" }), makeItem({ id: "c" })], 5, 3);

      const state = useQueueStore.getState();
      expect(state.items).toHaveLength(2);
      expect(state.items[0].id).toBe("b");
      expect(state.items[1].id).toBe("c");
      expect(state.total).toBe(5);
      expect(state.pending).toBe(3);
    });

    it("preserves selectedItemId when item still exists", () => {
      const store = useQueueStore.getState();
      store.mergeItems([makeItem({ id: "a" }), makeItem({ id: "b" })], 2, 2);
      store.selectItem("b");

      useQueueStore
        .getState()
        .mergeItems([makeItem({ id: "a" }), makeItem({ id: "b" })], 2, 1);

      expect(useQueueStore.getState().selectedItemId).toBe("b");
    });

    it("preserves selectedItemId even if item removed (no auto-clear)", () => {
      const store = useQueueStore.getState();
      store.mergeItems([makeItem({ id: "a" }), makeItem({ id: "b" })], 2, 2);
      store.selectItem("b");

      // New data doesn't include "b"
      useQueueStore.getState().mergeItems([makeItem({ id: "a" })], 1, 1);

      // Selection is preserved (design says preserve selectedItemId)
      expect(useQueueStore.getState().selectedItemId).toBe("b");
    });

    it("preserves optimistic statuses across merges", () => {
      const store = useQueueStore.getState();
      store.applyOptimisticUpdate("item-1", "approved");

      useQueueStore.getState().mergeItems([makeItem({ id: "item-1" })], 1, 0);

      expect(useQueueStore.getState().optimisticStatuses).toEqual({
        "item-1": "approved",
      });
    });
  });

  describe("selectItem", () => {
    it("sets selectedItemId", () => {
      useQueueStore.getState().selectItem("item-42");
      expect(useQueueStore.getState().selectedItemId).toBe("item-42");
    });
  });

  describe("applyOptimisticUpdate", () => {
    it("adds optimistic status entry", () => {
      useQueueStore.getState().applyOptimisticUpdate("item-1", "approved");
      expect(useQueueStore.getState().optimisticStatuses).toEqual({
        "item-1": "approved",
      });
    });

    it("can track multiple items", () => {
      const store = useQueueStore.getState();
      store.applyOptimisticUpdate("item-1", "approved");
      useQueueStore.getState().applyOptimisticUpdate("item-2", "rejected");

      expect(useQueueStore.getState().optimisticStatuses).toEqual({
        "item-1": "approved",
        "item-2": "rejected",
      });
    });
  });

  describe("rollbackOptimisticUpdate", () => {
    it("removes the optimistic status entry", () => {
      const store = useQueueStore.getState();
      store.applyOptimisticUpdate("item-1", "approved");
      store.applyOptimisticUpdate("item-2", "rejected");

      useQueueStore.getState().rollbackOptimisticUpdate("item-1");

      expect(useQueueStore.getState().optimisticStatuses).toEqual({
        "item-2": "rejected",
      });
    });
  });

  describe("clearOptimisticUpdate", () => {
    it("removes the optimistic status entry (server now matches)", () => {
      const store = useQueueStore.getState();
      store.applyOptimisticUpdate("item-1", "approved");

      useQueueStore.getState().clearOptimisticUpdate("item-1");

      expect(useQueueStore.getState().optimisticStatuses).toEqual({});
    });
  });

  describe("setFilters", () => {
    it("updates filter state", () => {
      useQueueStore
        .getState()
        .setFilters({ itemType: "finding", unverifiableOnly: true });

      const state = useQueueStore.getState();
      expect(state.filters.itemType).toBe("finding");
      expect(state.filters.unverifiableOnly).toBe(true);
    });
  });

  describe("setSortBy", () => {
    it("updates sort field and direction", () => {
      useQueueStore.getState().setSortBy("item_type", "desc");

      const state = useQueueStore.getState();
      expect(state.sortBy).toBe("item_type");
      expect(state.sortDirection).toBe("desc");
    });
  });

  describe("reset", () => {
    it("clears all state back to initial", () => {
      const store = useQueueStore.getState();
      store.setRunId("run-1");
      store.mergeItems([makeItem()], 1, 1);
      store.selectItem("item-1");
      store.applyOptimisticUpdate("item-1", "approved");
      store.setFilters({ itemType: "conflict", unverifiableOnly: true });
      store.setSortBy("item_type", "desc");

      useQueueStore.getState().reset();

      const state = useQueueStore.getState();
      expect(state.runId).toBeNull();
      expect(state.items).toEqual([]);
      expect(state.total).toBe(0);
      expect(state.pending).toBe(0);
      expect(state.selectedItemId).toBeNull();
      expect(state.optimisticStatuses).toEqual({});
      expect(state.filters).toEqual({
        itemType: null,
        unverifiableOnly: false,
      });
      expect(state.sortBy).toBe("queued_at");
      expect(state.sortDirection).toBe("asc");
    });
  });
});
