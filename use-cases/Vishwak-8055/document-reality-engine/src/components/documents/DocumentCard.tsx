import { Link } from "react-router-dom";
import { computeRisk } from "../../domain/risk";
import { computeCompliance } from "../../domain/compliance";
import { computeClaimsSummary } from "../../domain/claims";
import { formatDate } from "../../domain/utils";
import { DocumentStatusBadge, RiskLevelBadge } from "../ui/Badge";
import type { SDDocument } from "../../types/domain";

export function DocumentCard({ document }: { document: SDDocument }) {
  const risk = computeRisk(document);
  const compliance = computeCompliance(document.requirements);
  const claims = computeClaimsSummary(document.claims);

  return (
    <Link
      to={`/documents/${document.id}`}
      className="shadow-panel flex flex-col gap-3 rounded-md border border-line bg-paper-0 p-4 transition-colors hover:border-line-strong"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-text-tertiary">{document.type}</p>
          <h3 className="mt-0.5 line-clamp-2 text-sm font-semibold text-text-primary">{document.title}</h3>
        </div>
        <RiskLevelBadge level={risk.level} />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <DocumentStatusBadge status={document.status} />
        <span className="font-numeric text-xs text-text-tertiary">v{document.version}</span>
      </div>

      <dl className="mt-1 grid grid-cols-3 gap-2 border-t border-line pt-3 text-center">
        <div>
          <dt className="text-[10px] uppercase tracking-wide text-text-tertiary">Compliance</dt>
          <dd className="font-numeric text-sm font-semibold text-text-primary">{compliance.scorePercent}%</dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-wide text-text-tertiary">Claims</dt>
          <dd className="font-numeric text-sm font-semibold text-text-primary">
            {claims.verified}/{claims.total}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-wide text-text-tertiary">Risks</dt>
          <dd className="font-numeric text-sm font-semibold text-text-primary">{risk.openCount}</dd>
        </div>
      </dl>

      <p className="truncate text-xs text-text-tertiary">
        {document.owner.name} · updated {formatDate(document.updatedAt)}
      </p>
    </Link>
  );
}
