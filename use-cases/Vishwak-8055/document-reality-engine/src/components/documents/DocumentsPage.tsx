import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { computeRisk } from "../../domain/risk";
import { DocumentCard } from "./DocumentCard";
import { EmptyState } from "../ui/EmptyState";
import type { DocumentStatus, RiskLevel } from "../../types/domain";

const STATUS_OPTIONS = ["All", "Draft", "In Review", "Approved", "Published", "Deprecated"] as const;
const RISK_OPTIONS = ["All", "Critical", "High", "Medium", "Low"] as const;

type StatusFilter = (typeof STATUS_OPTIONS)[number];
type RiskFilter = (typeof RISK_OPTIONS)[number];

export function DocumentsPage() {
  const documents = useAppStore((s) => s.documents);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("All");
  const [riskLevel, setRiskLevel] = useState<RiskFilter>("All");

  const filtered = useMemo(() => {
    return documents.filter((doc) => {
      if (status !== "All" && doc.status !== (status as DocumentStatus)) return false;
      if (riskLevel !== "All" && computeRisk(doc).level !== (riskLevel as RiskLevel)) return false;
      if (query.trim()) {
        const q = query.trim().toLowerCase();
        const haystack = `${doc.title} ${doc.counterparty ?? ""} ${doc.owner.name}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [documents, status, riskLevel, query]);

  const filtersActive = status !== "All" || riskLevel !== "All" || query.trim() !== "";

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight text-text-primary">Documents</h1>
        <p className="mt-1 text-sm text-text-tertiary">{documents.length} documents in the workspace.</p>
      </div>

      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex flex-1 items-center gap-2 rounded-md border border-line bg-paper-0 px-3 py-2">
          <Search className="h-4 w-4 shrink-0 text-text-tertiary" aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by title, counterparty, or owner…"
            aria-label="Search documents"
            className="w-full bg-transparent text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none"
          />
        </div>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value as StatusFilter)}
          aria-label="Filter by status"
          className="rounded-md border border-line bg-paper-0 px-3 py-2 text-sm text-text-primary"
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option === "All" ? "All statuses" : option}
            </option>
          ))}
        </select>
        <select
          value={riskLevel}
          onChange={(event) => setRiskLevel(event.target.value as RiskFilter)}
          aria-label="Filter by risk level"
          className="rounded-md border border-line bg-paper-0 px-3 py-2 text-sm text-text-primary"
        >
          {RISK_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option === "All" ? "All risk levels" : `${option} risk`}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={Search}
          title="No documents match your filters"
          description={filtersActive ? "Try a different search term, or clear the status and risk filters." : "There are no documents in the workspace yet."}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((doc) => (
            <DocumentCard key={doc.id} document={doc} />
          ))}
        </div>
      )}
    </div>
  );
}
