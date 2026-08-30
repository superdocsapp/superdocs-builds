import { Link } from "react-router-dom";
import { ClipboardCheck } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { computeRisk } from "../../domain/risk";
import { unresolvedRequirements } from "../../domain/compliance";
import { formatDate, pluralize } from "../../domain/utils";
import { DocumentStatusBadge, RiskLevelBadge } from "../ui/Badge";
import { EmptyState } from "../ui/EmptyState";

export function ReviewsPage() {
  const documents = useAppStore((s) => s.documents);

  const queue = documents
    .filter((doc) => doc.status === "Draft" || doc.status === "In Review")
    .map((doc) => ({
      document: doc,
      risk: computeRisk(doc),
      unresolved: unresolvedRequirements(doc.requirements),
      openActions: doc.actions.filter((a) => a.status !== "Done"),
    }))
    .sort((a, b) => b.risk.score - a.risk.score);

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8 md:py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight text-text-primary">Reviews</h1>
        <p className="mt-1 text-sm text-text-tertiary">
          {queue.length} {pluralize(queue.length, "document")} awaiting a decision.
        </p>
      </div>

      {queue.length === 0 ? (
        <EmptyState icon={ClipboardCheck} title="Nothing in the review queue" description="Every document in the workspace has reached a final decision." />
      ) : (
        <ul className="divide-y divide-line rounded-md border border-line bg-paper-0">
          {queue.map(({ document, risk, unresolved, openActions }) => (
            <li key={document.id}>
              <Link
                to={`/documents/${document.id}/reviews`}
                className="flex flex-col gap-2 px-5 py-4 transition-colors hover:bg-paper-50 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-text-primary">{document.title}</p>
                  <p className="mt-1 text-xs text-text-tertiary">
                    {document.owner.name} · updated {formatDate(document.updatedAt)} · {unresolved.length} unresolved{" "}
                    {pluralize(unresolved.length, "requirement")} · {openActions.length} open {pluralize(openActions.length, "action")}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <DocumentStatusBadge status={document.status} />
                  <RiskLevelBadge level={risk.level} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
