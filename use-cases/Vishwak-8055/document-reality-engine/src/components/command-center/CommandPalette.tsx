import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, ClipboardCheck, FileText, Quote, Search, ShieldAlert, Stamp, User } from "lucide-react";
import clsx from "clsx";
import { useAppStore } from "../../store/appStore";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { COMMANDS, runSearch, type SearchResult, type SearchResultKind } from "../../domain/search";

const KIND_ICON: Record<SearchResultKind, typeof FileText> = {
  Document: FileText,
  Claim: Quote,
  Evidence: Stamp,
  Requirement: ClipboardCheck,
  Risk: ShieldAlert,
  Reviewer: User,
};

export function CommandPalette() {
  const open = useAppStore((s) => s.commandPaletteOpen);
  const close = useAppStore((s) => s.closeCommandPalette);
  const documents = useAppStore((s) => s.documents);
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useFocusTrap<HTMLDivElement>(open, close);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
    }
  }, [open]);

  const outcome = useMemo(() => runSearch(documents, query), [documents, query]);
  const results = outcome.results;

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  function go(result: SearchResult) {
    navigate(result.navigateTo);
    close();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (results.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => (i + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => (i - 1 + results.length) % results.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const target = results[activeIndex];
      if (target) go(target);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]">
      <button aria-label="Close search" onClick={close} className="absolute inset-0 bg-ink-950/50" style={{ animation: "sd-fade-in 150ms ease-out" }} />
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-label="Search SuperDocs"
        className="shadow-elevated relative flex max-h-[70vh] w-full max-w-xl flex-col overflow-hidden rounded-md bg-paper-0"
        style={{ animation: "sd-pop-in 160ms ease-out" }}
      >
        <div className="flex items-center gap-2.5 border-b border-line px-4 py-3">
          <Search className="h-4 w-4 shrink-0 text-text-tertiary" aria-hidden="true" />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search documents, claims, evidence — or try a command…"
            aria-label="Search SuperDocs"
            className="w-full bg-transparent text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none"
          />
          <kbd className="font-numeric shrink-0 rounded border border-line-strong px-1.5 py-0.5 text-[10px] text-text-tertiary">Esc</kbd>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {query.trim() === "" ? (
            <div>
              <p className="px-2 pb-1.5 pt-1 text-[11px] font-medium uppercase tracking-wide text-text-tertiary">Try a command</p>
              {COMMANDS.map((command) => (
                <button
                  key={command.id}
                  onClick={() => setQuery(command.label)}
                  className="flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-paper-100"
                >
                  <span>
                    <span className="block font-medium text-text-primary">{command.label}</span>
                    <span className="block text-xs text-text-tertiary">{command.description}</span>
                  </span>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-text-tertiary" aria-hidden="true" />
                </button>
              ))}
            </div>
          ) : results.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-text-tertiary">No matches for &ldquo;{query}&rdquo;.</p>
          ) : (
            <div>
              {outcome.matchedCommand && (
                <p className="px-2 pb-1.5 pt-1 text-[11px] font-medium uppercase tracking-wide text-text-tertiary">{outcome.matchedCommand.label}</p>
              )}
              {results.map((result, index) => {
                const Icon = KIND_ICON[result.kind];
                return (
                  <button
                    key={`${result.kind}-${result.id}`}
                    onClick={() => go(result)}
                    onMouseEnter={() => setActiveIndex(index)}
                    className={clsx(
                      "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors",
                      index === activeIndex ? "bg-trust-soft" : "hover:bg-paper-100",
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0 text-text-secondary" aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-text-primary">{result.title}</span>
                      <span className="block truncate text-xs text-text-tertiary">{result.subtitle}</span>
                    </span>
                    <span className="shrink-0 rounded border border-line px-1.5 py-0.5 text-[10px] text-text-tertiary">{result.kind}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
