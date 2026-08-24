"use client";

import {
  useCallback,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";

import {
  CONVERSATION_DEFAULT_WIDTH,
  CONVERSATION_MAX_WIDTH,
  CONVERSATION_MIN_WIDTH,
  clampConversationWidth,
  conversationWidthServerSnapshot,
  conversationWidthSnapshot,
  setConversationWidth,
  subscribeToConversationWidth,
} from "../lib/ui-preferences";

const KEYBOARD_STEP = 24;

/**
 * The split width as a style for the workbench container. Screens that render
 * the workbench geometry without a draggable divider — import, and the
 * unavailable-source state — use this so arriving in the workbench never
 * shifts the panes.
 */
export function useConversationWidthStyle(): CSSProperties {
  const width = useSyncExternalStore(
    subscribeToConversationWidth,
    conversationWidthSnapshot,
    conversationWidthServerSnapshot,
  );
  return { "--conversation-w": `${width}px` } as CSSProperties;
}

/** Content width available to the two panes, gutter excluded. */
function measureAvailable(element: HTMLElement): number {
  const styles = getComputedStyle(element);
  const gutter = Number.parseFloat(styles.getPropertyValue("--workbench-gutter")) || 0;
  const paddingX =
    (Number.parseFloat(styles.paddingLeft) || 0) + (Number.parseFloat(styles.paddingRight) || 0);
  return Math.max(0, element.clientWidth - paddingX - gutter);
}

type HandleProps = {
  role: "separator";
  tabIndex: 0;
  "aria-orientation": "vertical";
  "aria-label": string;
  "aria-valuenow": number;
  "aria-valuemin": number;
  "aria-valuemax": number;
  "data-dragging": "true" | "false";
  className: string;
  onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerMove: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerCancel: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
  onDoubleClick: () => void;
};

/**
 * Editor-style split between the conversation and the document.
 *
 * The preference is a single number. Everything that depends on the current
 * viewport — keeping the document pane usable, and ignoring the split entirely
 * on narrow screens — is expressed in CSS on `--conversation-w`, so no layout
 * measurement runs during render and nothing has to be re-clamped when the
 * window resizes. Persistence is per-browser localStorage.
 */
export function useConversationSplit(): {
  containerRef: RefObject<HTMLDivElement | null>;
  containerStyle: CSSProperties;
  handleProps: HandleProps;
} {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ startX: number; startWidth: number; max: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  const width = useSyncExternalStore(
    subscribeToConversationWidth,
    conversationWidthSnapshot,
    conversationWidthServerSnapshot,
  );

  const onPointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const container = containerRef.current;
    if (!container) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const pane = container.firstElementChild;
    const startWidth = pane instanceof HTMLElement ? pane.getBoundingClientRect().width : width;
    dragRef.current = {
      startX: event.clientX,
      startWidth,
      max: measureAvailable(container),
    };
    setDragging(true);
    document.body.classList.add("split-active");
  }, [width]);

  const onPointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    setConversationWidth(
      clampConversationWidth(drag.startWidth + (event.clientX - drag.startX), drag.max),
    );
  }, []);

  const endDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    setDragging(false);
    document.body.classList.remove("split-active");
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setConversationWidth(conversationWidthSnapshot(), true);
  }, []);

  const onKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    const container = containerRef.current;
    const current = conversationWidthSnapshot();
    let next: number | null = null;
    if (event.key === "ArrowLeft") next = current - KEYBOARD_STEP;
    else if (event.key === "ArrowRight") next = current + KEYBOARD_STEP;
    else if (event.key === "Home") next = CONVERSATION_MIN_WIDTH;
    else if (event.key === "End") next = CONVERSATION_MAX_WIDTH;
    else if (event.key === "Enter" || event.key === " ") next = CONVERSATION_DEFAULT_WIDTH;
    if (next === null) return;
    event.preventDefault();
    setConversationWidth(
      clampConversationWidth(next, container ? measureAvailable(container) : undefined),
      true,
    );
  }, []);

  const onDoubleClick = useCallback(() => {
    setConversationWidth(CONVERSATION_DEFAULT_WIDTH, true);
  }, []);

  return {
    containerRef,
    containerStyle: { "--conversation-w": `${width}px` } as CSSProperties,
    handleProps: {
      role: "separator",
      tabIndex: 0,
      "aria-orientation": "vertical",
      "aria-label": "Resize conversation pane",
      "aria-valuenow": width,
      "aria-valuemin": CONVERSATION_MIN_WIDTH,
      "aria-valuemax": CONVERSATION_MAX_WIDTH,
      "data-dragging": dragging ? "true" : "false",
      className: "split-handle",
      onPointerDown,
      onPointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
      onKeyDown,
      onDoubleClick,
    },
  };
}
