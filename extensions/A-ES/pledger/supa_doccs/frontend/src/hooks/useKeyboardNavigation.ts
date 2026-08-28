import { useEffect, useCallback } from 'react';
import type { QueueItem } from '@/types/review';

export interface UseKeyboardNavigationProps {
  items: QueueItem[];
  selectedItemId: string | null;
  onSelectItem: (itemId: string) => void;
  listRef: React.RefObject<HTMLElement>;
  approveButtonRef: React.RefObject<HTMLButtonElement>;
  rejectButtonRef: React.RefObject<HTMLButtonElement>;
}

/**
 * Hook providing keyboard navigation for the review queue interface.
 *
 * - ArrowUp/ArrowDown: navigate between queue items
 * - Enter: handled by individual cards (no-op here)
 * - 'a': focus the Approve button
 * - 'r': focus the Reject button
 * - Escape: return focus to the Queue List
 *
 * Shortcuts are suppressed when the user is typing in an input, textarea,
 * or contenteditable element.
 */
export function useKeyboardNavigation({
  items,
  selectedItemId,
  onSelectItem,
  listRef,
  approveButtonRef,
  rejectButtonRef,
}: UseKeyboardNavigationProps): void {
  const isTyping = useCallback((event: KeyboardEvent): boolean => {
    const target = event.target as HTMLElement | null;
    if (!target || !target.tagName) return false;
    const tagName = target.tagName.toLowerCase();
    if (tagName === 'input' || tagName === 'textarea' || tagName === 'select') {
      return true;
    }
    if (target.isContentEditable) {
      return true;
    }
    return false;
  }, []);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      // Don't intercept when user is typing in form fields
      if (isTyping(event)) return;

      switch (event.key) {
        case 'ArrowUp': {
          event.preventDefault();
          if (items.length === 0) return;
          const currentIndex = items.findIndex((item) => item.id === selectedItemId);
          const prevIndex = currentIndex <= 0 ? 0 : currentIndex - 1;
          onSelectItem(items[prevIndex].id);
          break;
        }

        case 'ArrowDown': {
          event.preventDefault();
          if (items.length === 0) return;
          const currentIndex = items.findIndex((item) => item.id === selectedItemId);
          const nextIndex =
            currentIndex === -1 ? 0 : Math.min(currentIndex + 1, items.length - 1);
          onSelectItem(items[nextIndex].id);
          break;
        }

        case 'a': {
          if (approveButtonRef.current) {
            event.preventDefault();
            approveButtonRef.current.focus();
          }
          break;
        }

        case 'r': {
          if (rejectButtonRef.current) {
            event.preventDefault();
            rejectButtonRef.current.focus();
          }
          break;
        }

        case 'Escape': {
          if (listRef.current) {
            event.preventDefault();
            listRef.current.focus();
          }
          break;
        }

        default:
          break;
      }
    },
    [items, selectedItemId, onSelectItem, listRef, approveButtonRef, rejectButtonRef, isTyping],
  );

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleKeyDown]);
}
