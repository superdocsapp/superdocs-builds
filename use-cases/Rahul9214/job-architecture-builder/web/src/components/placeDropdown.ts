export type DropdownRect = {
  top: number;
  left: number;
  bottom: number;
  width: number;
};

export type DropdownViewport = {
  width: number;
  height: number;
  offsetLeft: number;
  offsetTop: number;
  layoutHeight: number;
};

export type DropdownPlacement = {
  top?: number;
  bottom?: number;
  left: number;
  width: number;
  maxHeight: number;
};

export function viewportGutter(width: number): number {
  return width >= 390 ? 16 : 12;
}

export function readDropdownViewport(): DropdownViewport {
  const view = window.visualViewport;
  return {
    width: view?.width ?? window.innerWidth,
    height: view?.height ?? window.innerHeight,
    offsetLeft: view?.offsetLeft ?? 0,
    offsetTop: view?.offsetTop ?? 0,
    layoutHeight: window.innerHeight,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function placeDropdown(
  trigger: DropdownRect,
  viewport: DropdownViewport,
  minContentWidth = 0,
  panelHeight = 0,
): DropdownPlacement {
  const gutter = viewportGutter(viewport.width);
  const maxWidth = Math.max(0, viewport.width - gutter * 2);
  const panelWidth = Math.min(Math.max(trigger.width, minContentWidth), maxWidth);
  const minLeft = viewport.offsetLeft + gutter;
  const maxLeft = viewport.offsetLeft + viewport.width - panelWidth - gutter;
  const left = maxLeft < minLeft ? minLeft : clamp(trigger.left, minLeft, maxLeft);

  const cap = Math.min(viewport.height * 0.5, 420);
  const gap = 6;
  const below = trigger.bottom + gap;
  const viewTop = viewport.offsetTop + gutter;
  const viewBottom = viewport.offsetTop + viewport.height - gutter;
  const spaceBelow = viewBottom - below;
  const spaceAbove = trigger.top - gap - viewTop;
  const openUp = spaceBelow < Math.min(160, cap) && spaceAbove > spaceBelow;
  const available = Math.max(44, openUp ? spaceAbove : spaceBelow);
  const maxHeight = Math.min(cap, available);

  if (openUp) {
    if (panelHeight > 0) {
      const height = Math.min(panelHeight, maxHeight);
      return {
        top: Math.max(viewTop, trigger.top - gap - height),
        left,
        width: panelWidth,
        maxHeight,
      };
    }
    return {
      bottom: Math.max(gutter, viewport.layoutHeight - trigger.top + gap),
      left,
      width: panelWidth,
      maxHeight,
    };
  }

  return { top: below, left, width: panelWidth, maxHeight };
}

export function placeDropdownForTrigger(
  trigger: HTMLElement,
  minContentWidth = 0,
  panelHeight = 0,
): DropdownPlacement {
  const rect = trigger.getBoundingClientRect();
  return placeDropdown(
    { top: rect.top, left: rect.left, bottom: rect.bottom, width: rect.width },
    readDropdownViewport(),
    minContentWidth,
    panelHeight,
  );
}
