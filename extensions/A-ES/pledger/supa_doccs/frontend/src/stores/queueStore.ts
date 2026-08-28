import { create } from "zustand";
import type {
  QueueItem,
  QueueFilters,
  SortField,
  ItemStatus,
} from "@/types/review";

export interface QueueState {
  runId: string | null;
  items: QueueItem[];
  total: number;
  pending: number;
  selectedItemId: string | null;
  optimisticStatuses: Record<string, ItemStatus>; // itemId → optimistic status
  filters: QueueFilters;
  sortBy: SortField;
  sortDirection: "asc" | "desc";

  // Actions
  setRunId: (runId: string) => void;
  mergeItems: (items: QueueItem[], total: number, pending: number) => void;
  selectItem: (itemId: string) => void;
  applyOptimisticUpdate: (itemId: string, status: ItemStatus) => void;
  rollbackOptimisticUpdate: (itemId: string) => void;
  clearOptimisticUpdate: (itemId: string) => void;
  setFilters: (filters: QueueFilters) => void;
  setSortBy: (field: SortField, direction: "asc" | "desc") => void;
  reset: () => void;
}

const initialState = {
  runId: null as string | null,
  items: [] as QueueItem[],
  total: 0,
  pending: 0,
  selectedItemId: null as string | null,
  optimisticStatuses: {} as Record<string, ItemStatus>,
  filters: { itemType: null, unverifiableOnly: false } as QueueFilters,
  sortBy: "queued_at" as SortField,
  sortDirection: "asc" as "asc" | "desc",
};

export const useQueueStore = create<QueueState>((set) => ({
  ...initialState,

  setRunId: (runId: string) =>
    set({
      runId,
      items: [],
      total: 0,
      pending: 0,
      selectedItemId: null,
      optimisticStatuses: {},
    }),

  mergeItems: (items: QueueItem[], total: number, pending: number) =>
    set((state) => ({
      items,
      total,
      pending,
      // Preserve selection if the selected item still exists in new data
      selectedItemId:
        state.selectedItemId &&
        items.some((item) => item.id === state.selectedItemId)
          ? state.selectedItemId
          : state.selectedItemId,
      // Preserve optimistic statuses — they override server data until cleared
      optimisticStatuses: state.optimisticStatuses,
    })),

  selectItem: (itemId: string) =>
    set({ selectedItemId: itemId }),

  applyOptimisticUpdate: (itemId: string, status: ItemStatus) =>
    set((state) => ({
      optimisticStatuses: {
        ...state.optimisticStatuses,
        [itemId]: status,
      },
    })),

  rollbackOptimisticUpdate: (itemId: string) =>
    set((state) => {
      const { [itemId]: _, ...rest } = state.optimisticStatuses;
      return { optimisticStatuses: rest };
    }),

  clearOptimisticUpdate: (itemId: string) =>
    set((state) => {
      const { [itemId]: _, ...rest } = state.optimisticStatuses;
      return { optimisticStatuses: rest };
    }),

  setFilters: (filters: QueueFilters) =>
    set({ filters }),

  setSortBy: (field: SortField, direction: "asc" | "desc") =>
    set({ sortBy: field, sortDirection: direction }),

  reset: () => set({ ...initialState }),
}));
