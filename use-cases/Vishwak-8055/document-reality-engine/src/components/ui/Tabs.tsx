import { useRef, type KeyboardEvent, type ReactNode } from "react";
import clsx from "clsx";

export interface TabItem {
  id: string;
  label: string;
  badge?: ReactNode;
}

export function Tabs({
  tabs,
  activeId,
  onChange,
  ariaLabel,
}: {
  tabs: TabItem[];
  activeId: string;
  onChange: (id: string) => void;
  ariaLabel: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  function focusTabAt(index: number) {
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    const target = buttons?.[index];
    target?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key === "ArrowRight") {
      event.preventDefault();
      const next = (index + 1) % tabs.length;
      onChange(tabs[next]!.id);
      focusTabAt(next);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      const prev = (index - 1 + tabs.length) % tabs.length;
      onChange(tabs[prev]!.id);
      focusTabAt(prev);
    } else if (event.key === "Home") {
      event.preventDefault();
      onChange(tabs[0]!.id);
      focusTabAt(0);
    } else if (event.key === "End") {
      event.preventDefault();
      onChange(tabs[tabs.length - 1]!.id);
      focusTabAt(tabs.length - 1);
    }
  }

  return (
    <div role="tablist" aria-label={ariaLabel} ref={listRef} className="scrollbar-none flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((tab, index) => {
        const selected = tab.id === activeId;
        return (
          <button
            key={tab.id}
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            className={clsx(
              "relative flex shrink-0 items-center gap-1.5 px-3.5 py-2.5 text-sm font-medium transition-colors",
              selected ? "text-trust" : "text-text-secondary hover:text-text-primary",
            )}
          >
            {tab.label}
            {tab.badge}
            {selected && <span aria-hidden="true" className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-trust" />}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ id, activeId, children }: { id: string; activeId: string; children: ReactNode }) {
  if (id !== activeId) return null;
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} tabIndex={0} className="focus:outline-none">
      {children}
    </div>
  );
}
