import { useCallback } from 'react';
import type { QueueItem } from '@/types/review';

export interface UseFocusManagementProps {
  items: QueueItem[];
  selectedItemId: string | null;
  onSelectItem: (itemId: string) => void;
  listRef: React.RefObject<HTMLElement>;
}

export interface UseFocusManagementReturn {
  advanceFocusAfterDecision: () => void;
}

/**
 * Manages focus advancement after a decision is submitted.
 * After a decision, focus moves to the next pending item in the queue list,
 * skipping items that have already been decided.
 *
 * Components using this hook should apply visible focus ring styling via Tailwind:
 *   focus:ring-2 focus:ring-offset-2 focus:ring-blue-500
 * These classes meet WCAG 2.1 AA contrast requirements for focus indicators.
 *
 * Validates: Requirements 9.4, 9.5
 */
export function useFocusManagement({
  items,
  selectedItemId,
  onSelectItem,
  listRef,
}: UseFocusManagementProps): UseFocusManagementReturn {
  const advanceFocusAfterDecision = useCallback(() => {
    if (!selectedItemId || items.length === 0) {
      // No selection or empty list — focus the list container as fallback
      listRef.current?.focus();
      return;
    }

    const currentIndex = items.findIndex((item) => item.id === selectedItemId);

    if (currentIndex === -1) {
      // Selected item not found in list — focus container
      listRef.current?.focus();
      return;
    }

    // Search forward from the next item for the first pending item
    let nextPendingItem: QueueItem | null = null;
    for (let i = currentIndex + 1; i < items.length; i++) {
      if (items[i].status === 'pending') {
        nextPendingItem = items[i];
        break;
      }
    }

    // If nothing found after current, wrap around and search from the beginning
    if (!nextPendingItem) {
      for (let i = 0; i < currentIndex; i++) {
        if (items[i].status === 'pending') {
          nextPendingItem = items[i];
          break;
        }
      }
    }

    if (nextPendingItem) {
      // Select the next pending item and focus its DOM element
      onSelectItem(nextPendingItem.id);

      // Focus the DOM element for the next pending item
      const itemElement = listRef.current?.querySelector(
        `[data-item-id="${nextPendingItem.id}"]`
      ) as HTMLElement | null;

      if (itemElement) {
        itemElement.focus();
      } else {
        // Element not yet rendered — focus the list container
        listRef.current?.focus();
      }
    } else {
      // No pending items remain — stay at current position, focus list container
      listRef.current?.focus();
    }
  }, [items, selectedItemId, onSelectItem, listRef]);

  return { advanceFocusAfterDecision };
}
