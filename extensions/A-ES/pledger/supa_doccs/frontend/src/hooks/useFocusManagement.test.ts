import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { useFocusManagement } from './useFocusManagement';
import type { QueueItem } from '@/types/review';

function makeItem(id: string, status: 'pending' | 'approved' | 'rejected'): QueueItem {
  return {
    id,
    run_id: 'run-1',
    item_type: 'finding',
    payload: { summary: `Item ${id}`, details: {}, source_citations: [] },
    status,
    queued_at: '2024-01-01T00:00:00Z',
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
  };
}

function createMockListRef(itemIds: string[] = []) {
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

describe('useFocusManagement', () => {
  it('advances focus to the next pending item after current selection', () => {
    const items = [
      makeItem('a', 'approved'),
      makeItem('b', 'pending'), // selected
      makeItem('c', 'approved'),
      makeItem('d', 'pending'), // should receive focus
      makeItem('e', 'pending'),
    ];

    const onSelectItem = vi.fn();
    const { ref, getItemFocus } = createMockListRef(['a', 'b', 'c', 'd', 'e']);

    const { result } = renderHook(() =>
      useFocusManagement({
        items,
        selectedItemId: 'b',
        onSelectItem,
        listRef: ref,
      })
    );

    act(() => {
      result.current.advanceFocusAfterDecision();
    });

    expect(onSelectItem).toHaveBeenCalledWith('d');
    expect(getItemFocus('d')).toHaveBeenCalled();
  });

  it('wraps around to find pending items before the current index', () => {
    const items = [
      makeItem('a', 'pending'), // should receive focus (wrap)
      makeItem('b', 'approved'),
      makeItem('c', 'pending'), // selected — just decided
      makeItem('d', 'rejected'),
      makeItem('e', 'rejected'),
    ];

    const onSelectItem = vi.fn();
    const { ref, getItemFocus } = createMockListRef(['a', 'b', 'c', 'd', 'e']);

    const { result } = renderHook(() =>
      useFocusManagement({
        items,
        selectedItemId: 'c',
        onSelectItem,
        listRef: ref,
      })
    );

    act(() => {
      result.current.advanceFocusAfterDecision();
    });

    expect(onSelectItem).toHaveBeenCalledWith('a');
    expect(getItemFocus('a')).toHaveBeenCalled();
  });

  it('focuses list container when no pending items remain', () => {
    const items = [
      makeItem('a', 'approved'),
      makeItem('b', 'rejected'),
      makeItem('c', 'approved'), // selected
    ];

    const onSelectItem = vi.fn();
    const { ref, containerFocus } = createMockListRef(['a', 'b', 'c']);

    const { result } = renderHook(() =>
      useFocusManagement({
        items,
        selectedItemId: 'c',
        onSelectItem,
        listRef: ref,
      })
    );

    act(() => {
      result.current.advanceFocusAfterDecision();
    });

    expect(onSelectItem).not.toHaveBeenCalled();
    expect(containerFocus).toHaveBeenCalled();
  });

  it('focuses list container when selectedItemId is null', () => {
    const items = [makeItem('a', 'pending')];
    const onSelectItem = vi.fn();
    const { ref, containerFocus } = createMockListRef(['a']);

    const { result } = renderHook(() =>
      useFocusManagement({
        items,
        selectedItemId: null,
        onSelectItem,
        listRef: ref,
      })
    );

    act(() => {
      result.current.advanceFocusAfterDecision();
    });

    expect(onSelectItem).not.toHaveBeenCalled();
    expect(containerFocus).toHaveBeenCalled();
  });

  it('focuses list container when items list is empty', () => {
    const onSelectItem = vi.fn();
    const { ref, containerFocus } = createMockListRef([]);

    const { result } = renderHook(() =>
      useFocusManagement({
        items: [],
        selectedItemId: 'a',
        onSelectItem,
        listRef: ref,
      })
    );

    act(() => {
      result.current.advanceFocusAfterDecision();
    });

    expect(onSelectItem).not.toHaveBeenCalled();
    expect(containerFocus).toHaveBeenCalled();
  });

  it('focuses list container when selected item is not in the list', () => {
    const items = [makeItem('a', 'pending'), makeItem('b', 'pending')];
    const onSelectItem = vi.fn();
    const { ref, containerFocus } = createMockListRef(['a', 'b']);

    const { result } = renderHook(() =>
      useFocusManagement({
        items,
        selectedItemId: 'nonexistent',
        onSelectItem,
        listRef: ref,
      })
    );

    act(() => {
      result.current.advanceFocusAfterDecision();
    });

    expect(onSelectItem).not.toHaveBeenCalled();
    expect(containerFocus).toHaveBeenCalled();
  });

  it('falls back to list container focus when DOM element not found for next item', () => {
    const items = [
      makeItem('a', 'pending'), // selected
      makeItem('b', 'pending'), // next pending
    ];

    const onSelectItem = vi.fn();
    // Only register 'a' in the DOM mock, not 'b'
    const { ref, containerFocus } = createMockListRef(['a']);

    const { result } = renderHook(() =>
      useFocusManagement({
        items,
        selectedItemId: 'a',
        onSelectItem,
        listRef: ref,
      })
    );

    act(() => {
      result.current.advanceFocusAfterDecision();
    });

    expect(onSelectItem).toHaveBeenCalledWith('b');
    // Since 'b' DOM element doesn't exist, falls back to container
    expect(containerFocus).toHaveBeenCalled();
  });
});
