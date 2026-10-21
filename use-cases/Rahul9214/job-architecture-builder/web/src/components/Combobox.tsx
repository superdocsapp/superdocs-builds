import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { DropdownPopover } from "./DropdownPopover";
import { placeDropdownForTrigger, type DropdownPlacement } from "./placeDropdown";

export type ComboboxOption = {
  id: string;
  label: string;
  secondary?: string;
};

export type ComboboxProps = {
  id: string;
  label: string;
  value: string;
  options: ComboboxOption[];
  onChange: (id: string) => void;
  searchable?: boolean;
  hideLabel?: boolean;
  layout?: "stack" | "inline";
  placeholder?: string;
};

export function Combobox({
  id,
  label,
  value,
  options,
  onChange,
  searchable = true,
  hideLabel = false,
  layout = "stack",
  placeholder = "Select…",
}: ComboboxProps) {
  const listId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [pos, setPos] = useState<DropdownPlacement>({ top: 0, left: 0, width: 280, maxHeight: 320 });

  const selected = options.find((item) => item.id === value);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    return options.filter(
      (item) =>
        item.label.toLowerCase().includes(needle) ||
        (item.secondary ?? "").toLowerCase().includes(needle),
    );
  }, [options, query]);

  const filteredRef = useRef(filtered);
  const activeIndexRef = useRef(activeIndex);
  const onChangeRef = useRef(onChange);
  const searchableRef = useRef(searchable);
  filteredRef.current = filtered;
  activeIndexRef.current = activeIndex;
  onChangeRef.current = onChange;
  searchableRef.current = searchable;

  function close(restoreFocus = true) {
    setOpen(false);
    setQuery("");
    if (restoreFocus) triggerRef.current?.focus();
  }

  function reposition() {
    if (!triggerRef.current) return;
    const height = panelRef.current?.getBoundingClientRect().height ?? 0;
    setPos(placeDropdownForTrigger(triggerRef.current, searchableRef.current ? 280 : 0, height));
  }

  function openPanel() {
    reposition();
    const index = Math.max(
      0,
      options.findIndex((item) => item.id === value),
    );
    setActiveIndex(index === -1 ? 0 : index);
    setOpen(true);
  }

  function selectOption(option: ComboboxOption) {
    onChangeRef.current(option.id);
    close();
  }

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const height = panelRef.current?.getBoundingClientRect().height ?? 0;
    setPos(placeDropdownForTrigger(triggerRef.current, searchable ? 280 : 0, height));
  }, [open, searchable, filtered.length, query]);

  useEffect(() => {
    if (!open) return;
    if (searchable) searchRef.current?.focus();
    else panelRef.current?.focus();

    function onPointer(event: MouseEvent) {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      close(false);
    }

    function onKey(event: globalThis.KeyboardEvent) {
      const items = filteredRef.current;
      const current = activeIndexRef.current;
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key === "Tab") {
        close(false);
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex(Math.min(items.length - 1, current + 1));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex(Math.max(0, current - 1));
        return;
      }
      if (event.key === "Home") {
        event.preventDefault();
        setActiveIndex(0);
        return;
      }
      if (event.key === "End") {
        event.preventDefault();
        setActiveIndex(Math.max(0, items.length - 1));
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const option = items[current];
        if (option) selectOption(option);
      }
    }

    function onReposition() {
      reposition();
    }

    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onReposition);
    window.addEventListener("orientationchange", onReposition);
    window.addEventListener("scroll", onReposition, true);
    window.visualViewport?.addEventListener("resize", onReposition);
    window.visualViewport?.addEventListener("scroll", onReposition);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onReposition);
      window.removeEventListener("orientationchange", onReposition);
      window.removeEventListener("scroll", onReposition, true);
      window.visualViewport?.removeEventListener("resize", onReposition);
      window.visualViewport?.removeEventListener("scroll", onReposition);
    };
    // Listeners stay bound for the open lifetime; latest option state is read from refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, searchable]);

  useEffect(() => {
    if (activeIndex >= filtered.length) setActiveIndex(0);
  }, [activeIndex, filtered.length]);

  function onTriggerKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!open) openPanel();
    }
  }

  const active = filtered[activeIndex];

  return (
    <div className={`dropdown${layout === "inline" ? " is-inline" : ""}`}>
      <label id={`${id}-label`} htmlFor={id} className={hideLabel ? "sr-only" : layout === "inline" ? "field-label" : undefined}>
        {label}
      </label>
      <button
        ref={triggerRef}
        type="button"
        id={id}
        className="dropdown-trigger"
        role="combobox"
        aria-labelledby={`${id}-label`}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={listId}
        aria-activedescendant={open && active ? `${id}-opt-${active.id}` : undefined}
        onClick={() => (open ? close() : openPanel())}
        onKeyDown={onTriggerKey}
      >
        <span className="dropdown-value">
          {selected ? (
            <>
              {selected.label}
              {selected.secondary ? <small>{selected.secondary}</small> : null}
            </>
          ) : (
            placeholder
          )}
        </span>
      </button>
      {open ? (
        <DropdownPopover
          panelRef={panelRef}
          pos={pos}
          search={
            searchable ? (
              <input
                ref={searchRef}
                type="search"
                className="dropdown-search"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setActiveIndex(0);
                }}
                aria-label={`Filter ${label}`}
                placeholder="Search"
              />
            ) : null
          }
        >
          <ul id={listId} className="dropdown-list scroll-hidden" role="listbox" aria-labelledby={`${id}-label`}>
            {filtered.length === 0 ? (
              <li className="dropdown-empty">No matching items.</li>
            ) : (
              filtered.map((item, index) => (
                <li
                  key={item.id}
                  id={`${id}-opt-${item.id}`}
                  role="option"
                  aria-selected={item.id === value}
                  className={`dropdown-option${index === activeIndex ? " is-active" : ""}${item.id === value ? " is-selected" : ""}`}
                  onMouseEnter={() => setActiveIndex(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => selectOption(item)}
                >
                  <span>{item.label}</span>
                  {item.secondary ? <small>{item.secondary}</small> : null}
                </li>
              ))
            )}
          </ul>
        </DropdownPopover>
      ) : null}
    </div>
  );
}
