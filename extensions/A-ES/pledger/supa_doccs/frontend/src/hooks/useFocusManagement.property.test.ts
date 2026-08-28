import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import * as fc from 'fast-check';
import { useFocusManagement } from './useFocusManagement';
import type { QueueItem } from '@/types/review';
import type { ItemStatus, ItemType } from '@/types/review';

/**
 * Property 14: Focus Advances After Decision
 *
 * For any successful decision submission, keyboard focus SHALL move to the next
 * item in the Queue_List that has "pending" status, or remain on the current
 * position if no pending items remain.
 *
 * **Validates: Requirements 9.4**
 */

// --- Generators ---

const itemStatusArb: fc.Arbitrary<ItemStatus> = fc.oneof(
  fc.constant('pending' as ItemStatus),
  fc.constant('approved' as ItemStatus),
  fc.constant('rejected' as ItemStatus)
);

const itemTypeArb: fc.Arbitrary<ItemType> = fc.oneof(
  fc.constant('finding' as ItemType),
  fc.constant('conflict' as ItemType),
  fc.constant('proposed_update' as ItemType)
);

function queueItemArb(id: string): fc.Arbitrary<QueueItem> {
  return fc.record({
    id: fc.constant(id),
    run_id: fc.constant('run-1'),
    item_type: itemTypeArb,
    payload: fc.constant({ summary: `Item ${id}`, details: {}, source_citations: [] }),
    status: itemStatusArb,
    queued_at: fc.constant('2024-01-01T00:00:00Z'),
    decided_at: fc.constant(null),
    decision: fc.constant(null),
    reviewer_id: fc.constant(null),
    justification: fc.constant(null),
  });
}

/**
 * Generates a non-empty array of QueueItems with unique IDs and a valid selectedItemId
 * that exists within the array.
 */
const focusScenarioArb = fc
  .integer({ min: 1, max: 30 })
  .chain((length) => {
    const ids = Array.from({ length }, (_, i) => `item-${i}`);
    const itemsArb = fc.tuple(...ids.map((id) => queueItemArb(id)));
    const selectedIndexArb = fc.integer({ min: 0, max: length - 1 });
    return fc.tuple(itemsArb, selectedIndexArb).map(([items, selectedIndex]) => ({
      items,
      selectedItemId: ids[selectedIndex],
      selectedIndex,
    }));
  });

// --- Helper to create a mock listRef ---

function createMockListRef(itemIds: string[]) {
  const focusMock = vi.fn();
  const elements = new Map<string, { focus: ReturnType<typeof vi.fn> }>();
  itemIds.forEach((id) => {
    elements.set(id, { focus: vi.fn() });
  });

  const container = {
    focus: focusMock,
    querySelector: (selector: string) => {
      const match = selector.match(/\[data-item-id="(.+?)"\]/);
      if (match) {
        return elements.get(match[1]) || null;
      }
      return null;
    },
  };

  return {
    ref: { current: container } as unknown as React.RefObject<HTMLElement>,
    containerFocus: focusMock,
    getItemFocus: (id: string) => elements.get(id)?.focus,
  };
}

// --- Property Test ---

describe('Property 14: Focus Advances After Decision', () => {
  it('focus moves to the next pending item after decision, or stays if none remain', () => {
    fc.assert(
      fc.property(focusScenarioArb, ({ items, selectedItemId, selectedIndex }) => {
        const onSelectItem = vi.fn();
        const itemIds = items.map((item) => item.id);
        const { ref } = createMockListRef(itemIds);

        const { result } = renderHook(() =>
          useFocusManagement({
            items,
            selectedItemId,
            onSelectItem,
            listRef: ref,
          })
        );

        act(() => {
          result.current.advanceFocusAfterDecision();
        });

        // Find the expected next pending item: search forward from current, then wrap
        let expectedNextPendingId: string | null = null;

        // Search forward from after the selected index
        for (let i = selectedIndex + 1; i < items.length; i++) {
          if (items[i].status === 'pending') {
            expectedNextPendingId = items[i].id;
            break;
          }
        }

        // If not found, wrap around and search from beginning up to selected index
        if (!expectedNextPendingId) {
          for (let i = 0; i < selectedIndex; i++) {
            if (items[i].status === 'pending') {
              expectedNextPendingId = items[i].id;
              break;
            }
          }
        }

        if (expectedNextPendingId) {
          // Focus should advance to the next pending item
          expect(onSelectItem).toHaveBeenCalledTimes(1);
          expect(onSelectItem).toHaveBeenCalledWith(expectedNextPendingId);
        } else {
          // No pending items remain — focus stays (onSelectItem not called)
          expect(onSelectItem).not.toHaveBeenCalled();
        }
      }),
      { numRuns: 100 }
    );
  });
});
