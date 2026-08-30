import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, ClipboardCheck, FileText, Quote, Search, ShieldAlert, Stamp, User } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { COMMANDS, runSearch, type SearchResultKind } from "../../domain/search";
import { EmptyState } from "../ui/EmptyState";

const KIND_ICON: Record<SearchResultKind, typeof FileText> = {
  Document: FileText,
  Claim: Quote,
  Evidence: Stamp,
  Requirement: ClipboardCheck,
  Risk: ShieldAlert,
  Reviewer: User,
};

export function CommandCenterPage() {
  const documents = useAppStore((s) => s.documents);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  const outcome = useMemo(() => runSearch(documents, query), [documents, query]);

  return (
    <div className="mx-auto max-w-3xl px-4 py-6 md:px-8 md:py-10">
      <div className="mb-6 text-center">
        <h1 className="text-xl font-semibold tracking-tight text-text-primary">Command Center</h1>
        <p className="mt-1 text-sm text-text-tertiary">Search everything in the workspace, or run a command.</p>
      </div>

      <div className="shadow-panel mb-6 flex items-center gap-2.5 rounded-md border border-line bg-paper-0 px-4 py-3">
        <Search className="h-4 w-4 shrink-0 text-text-tertiary" aria-hidden="true" />
        <input
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search documents, claims, evidence — or try a command…"
          aria-label="Search SuperDocs"
          className="w-full bg-transparent text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none"
        />
      </div>

      {query.trim() === "" ? (
        <div>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-tertiary">Try a command</h2>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {COMMANDS.map((command) => (
              <button
                key={command.id}
                onClick={() => setQuery(command.label)}
                className="flex items-center justify-between gap-2 rounded-md border border-line bg-paper-0 px-4 py-3 text-left transition-colors hover:border-line-strong hover:bg-paper-50"
              >
                <span>
                  <span className="block text-sm font-medium text-text-primary">{command.label}</span>
                  <span className="block text-xs text-text-tertiary">{command.description}</span>
                </span>
                <ArrowRight className="h-3.5 w-3.5 shrink-0 text-text-tertiary" aria-hidden="true" />
              </button>
            ))}
          </div>
        </div>
      ) : outcome.results.length === 0 ? (
        <EmptyState icon={Search} title={`No matches for "${query}"`} description="Try a different search term or one of the canned commands above." />
      ) : (
        <div>
          {outcome.matchedCommand && (
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-tertiary">{outcome.matchedCommand.label}</h2>
          )}
          <ul className="divide-y divide-line rounded-md border border-line bg-paper-0">
            {outcome.results.map((result) => {
              const Icon = KIND_ICON[result.kind];
              return (
                <li key={`${result.kind}-${result.id}`}>
                  <button
                    onClick={() => navigate(result.navigateTo)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-paper-50"
                  >
                    <Icon className="h-4 w-4 shrink-0 text-text-secondary" aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-text-primary">{result.title}</span>
                      <span className="block truncate text-xs text-text-tertiary">{result.subtitle}</span>
                    </span>
                    <span className="shrink-0 rounded border border-line px-1.5 py-0.5 text-[10px] text-text-tertiary">{result.kind}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
