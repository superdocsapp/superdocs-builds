import { renderHook } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { useKeyboardNavigation } from './useKeyboardNavigation';
import type { QueueItem } from '@/types/review';

function makeItem(id: string): QueueItem {
  return {
    id,
    run_id: 'run-1',
    item_type: 'finding',
    payload: {
      summary: `Item ${id}`,
      details: {},
      source_citations: [],
    },
    status: 'pending',
    queued_at: '2024-01-01T00:00:00Z',
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
  };
}

function createRef<T>(current: T | null = null) {
  return { current } as React.RefObject<T>;
}

function fireKey(key: string, target: EventTarget = document) {
  const event = new KeyboardEvent('keydown', {
    key,
    bubbles: true,
    cancelable: true,
  });
  Object.defineProperty(event, 'target', { value: target, writable: false });
  document.dispatchEvent(event);
}

describe('useKeyboardNavigation', () => {
  const items = [makeItem('a'), makeItem('b'), makeItem('c')];

  it('ArrowDown selects the next item', () => {
    const onSelectItem = vi.fn();
    renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: 'a',
        onSelectItem,
        listRef: createRef<HTMLElement>(),
        approveButtonRef: createRef<HTMLButtonElement>(),
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    fireKey('ArrowDown');
    expect(onSelectItem).toHaveBeenCalledWith('b');
  });

  it('ArrowUp selects the previous item', () => {
    const onSelectItem = vi.fn();
    renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: 'b',
        onSelectItem,
        listRef: createRef<HTMLElement>(),
        approveButtonRef: createRef<HTMLButtonElement>(),
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    fireKey('ArrowUp');
    expect(onSelectItem).toHaveBeenCalledWith('a');
  });

  it('ArrowUp at the top stays at first item', () => {
    const onSelectItem = vi.fn();
    renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: 'a',
        onSelectItem,
        listRef: createRef<HTMLElement>(),
        approveButtonRef: createRef<HTMLButtonElement>(),
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    fireKey('ArrowUp');
    expect(onSelectItem).toHaveBeenCalledWith('a');
  });

  it('ArrowDown at the bottom stays at last item', () => {
    const onSelectItem = vi.fn();
    renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: 'c',
        onSelectItem,
        listRef: createRef<HTMLElement>(),
        approveButtonRef: createRef<HTMLButtonElement>(),
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    fireKey('ArrowDown');
    expect(onSelectItem).toHaveBeenCalledWith('c');
  });

  it('ArrowDown with no selection selects first item', () => {
    const onSelectItem = vi.fn();
    renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: null,
        onSelectItem,
        listRef: createRef<HTMLElement>(),
        approveButtonRef: createRef<HTMLButtonElement>(),
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    fireKey('ArrowDown');
    expect(onSelectItem).toHaveBeenCalledWith('a');
  });

  it('"a" focuses the approve button', () => {
    const approveBtn = document.createElement('button');
    const focusSpy = vi.spyOn(approveBtn, 'focus');

    renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: 'a',
        onSelectItem: vi.fn(),
        listRef: createRef<HTMLElement>(),
        approveButtonRef: { current: approveBtn } as React.RefObject<HTMLButtonElement>,
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    fireKey('a');
    expect(focusSpy).toHaveBeenCalled();
  });

  it('"r" focuses the reject button', () => {
    const rejectBtn = document.createElement('button');
    const focusSpy = vi.spyOn(rejectBtn, 'focus');

    renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: 'a',
        onSelectItem: vi.fn(),
        listRef: createRef<HTMLElement>(),
        approveButtonRef: createRef<HTMLButtonElement>(),
        rejectButtonRef: { current: rejectBtn } as React.RefObject<HTMLButtonElement>,
      }),
    );

    fireKey('r');
    expect(focusSpy).toHaveBeenCalled();
  });

  it('Escape returns focus to list container', () => {
    const listEl = document.createElement('div');
    const focusSpy = vi.spyOn(listEl, 'focus');

    renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: 'a',
        onSelectItem: vi.fn(),
        listRef: { current: listEl } as React.RefObject<HTMLElement>,
        approveButtonRef: createRef<HTMLButtonElement>(),
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    fireKey('Escape');
    expect(focusSpy).toHaveBeenCalled();
  });

  it('does not trigger shortcuts when typing in an input', () => {
    const onSelectItem = vi.fn();
    renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: 'a',
        onSelectItem,
        listRef: createRef<HTMLElement>(),
        approveButtonRef: createRef<HTMLButtonElement>(),
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    const input = document.createElement('input');
    fireKey('ArrowDown', input);
    expect(onSelectItem).not.toHaveBeenCalled();
  });

  it('does not trigger shortcuts when typing in a textarea', () => {
    const approveBtn = document.createElement('button');
    const focusSpy = vi.spyOn(approveBtn, 'focus');

    renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: 'a',
        onSelectItem: vi.fn(),
        listRef: createRef<HTMLElement>(),
        approveButtonRef: { current: approveBtn } as React.RefObject<HTMLButtonElement>,
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    const textarea = document.createElement('textarea');
    fireKey('a', textarea);
    expect(focusSpy).not.toHaveBeenCalled();
  });

  it('does nothing when items array is empty', () => {
    const onSelectItem = vi.fn();
    renderHook(() =>
      useKeyboardNavigation({
        items: [],
        selectedItemId: null,
        onSelectItem,
        listRef: createRef<HTMLElement>(),
        approveButtonRef: createRef<HTMLButtonElement>(),
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    fireKey('ArrowDown');
    fireKey('ArrowUp');
    expect(onSelectItem).not.toHaveBeenCalled();
  });

  it('cleans up event listener on unmount', () => {
    const onSelectItem = vi.fn();
    const { unmount } = renderHook(() =>
      useKeyboardNavigation({
        items,
        selectedItemId: 'a',
        onSelectItem,
        listRef: createRef<HTMLElement>(),
        approveButtonRef: createRef<HTMLButtonElement>(),
        rejectButtonRef: createRef<HTMLButtonElement>(),
      }),
    );

    unmount();
    fireKey('ArrowDown');
    expect(onSelectItem).not.toHaveBeenCalled();
  });
});
