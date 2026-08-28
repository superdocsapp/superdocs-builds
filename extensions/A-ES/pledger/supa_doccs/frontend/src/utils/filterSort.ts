import type { QueueItem, QueueFilters, SortField } from "@/types/review";
import { itemIsUnverifiable } from "@/utils/citationHelpers";

/**
 * Applies active filters to a list of queue items.
 * - If filters.itemType is set, keeps only items matching that type.
 * - If filters.unverifiableOnly is true, keeps only items that are
 *   unverifiable per the shared itemIsUnverifiable definition
 *   (no citations, or every citation unverifiable/null-span).
 * Both filters can be active simultaneously (AND logic).
 */
export function applyFilters(items: QueueItem[], filters: QueueFilters): QueueItem[] {
  let result = items;

  if (filters.itemType !== null) {
    result = result.filter((item) => item.item_type === filters.itemType);
  }

  if (filters.unverifiableOnly) {
    result = result.filter((item) =>
      itemIsUnverifiable(item.payload.source_citations)
    );
  }

  return result;
}

/**
 * Sorts queue items by the given field and direction.
 * - "item_type": alphabetical sort on the item_type string.
 * - "queued_at": chronological sort on the queued_at ISO timestamp.
 * Direction "asc" = A-Z or earliest first; "desc" = Z-A or latest first.
 * Returns a new array without mutating the input.
 */
export function applySorting(
  items: QueueItem[],
  sortBy: SortField,
  direction: "asc" | "desc"
): QueueItem[] {
  const sorted = [...items];

  sorted.sort((a, b) => {
    let comparison: number;

    if (sortBy === "item_type") {
      comparison = a.item_type.localeCompare(b.item_type);
    } else {
      // sortBy === "queued_at"
      comparison = a.queued_at.localeCompare(b.queued_at);
    }

    return direction === "asc" ? comparison : -comparison;
  });

  return sorted;
}
