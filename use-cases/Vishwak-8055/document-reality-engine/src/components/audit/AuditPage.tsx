import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { History } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { formatDateTime } from "../../domain/utils";
import { EmptyState } from "../ui/EmptyState";

export function AuditPage() {
  const documents = useAppStore((s) => s.documents);
  const [documentFilter, setDocumentFilter] = useState<string>("All");

  const events = useMemo(
    () =>
      documents
        .flatMap((doc) => doc.reviewEvents.map((event) => ({ event, documentId: doc.id, documentTitle: doc.title })))
        .sort((a, b) => new Date(b.event.timestamp).getTime() - new Date(a.event.timestamp).getTime()),
    [documents],
  );

  const filtered = documentFilter === "All" ? events : events.filter((entry) => entry.documentId === documentFilter);

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8 md:py-8">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-text-primary">Audit</h1>
          <p className="mt-1 text-sm text-text-tertiary">{events.length} events across the workspace.</p>
        </div>
        <select
          value={documentFilter}
          onChange={(event) => setDocumentFilter(event.target.value)}
          aria-label="Filter by document"
          className="rounded-md border border-line bg-paper-0 px-3 py-2 text-sm text-text-primary"
        >
          <option value="All">All documents</option>
          {documents.map((doc) => (
            <option key={doc.id} value={doc.id}>
              {doc.title}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon={History} title="No audit events" description="Try a different document filter." />
      ) : (
        <ul className="divide-y divide-line rounded-md border border-line bg-paper-0">
          {filtered.map(({ event, documentId, documentTitle }) => (
            <li key={event.id}>
              <Link
                to={`/documents/${documentId}/timeline`}
                className="flex flex-col gap-1 px-5 py-3 transition-colors hover:bg-paper-50 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">{event.type}</p>
                  <p className="mt-0.5 truncate text-xs text-text-tertiary">{event.explanation}</p>
                </div>
                <div className="shrink-0 sm:text-right">
                  <p className="text-xs text-text-tertiary">{documentTitle}</p>
                  <p className="font-numeric text-xs text-text-tertiary">
                    {formatDateTime(event.timestamp)} · {event.actor}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
