import type { ReactNode, Ref } from "react";
import { createPortal } from "react-dom";
import type { DropdownPlacement } from "./placeDropdown";

export function DropdownPopover({
  panelRef,
  pos,
  search,
  children,
}: {
  panelRef: Ref<HTMLDivElement>;
  pos: DropdownPlacement;
  search?: ReactNode;
  children: ReactNode;
}) {
  return createPortal(
    <div
      ref={panelRef}
      className="dropdown-panel"
      tabIndex={-1}
      style={{
        top: pos.top,
        bottom: pos.bottom,
        left: pos.left,
        width: pos.width,
        maxHeight: pos.maxHeight,
      }}
    >
      {search}
      {children}
    </div>,
    document.body,
  );
}
