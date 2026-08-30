import { Link } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import type { RiskAssessment } from "../../domain/risk";
import { Badge, riskLevelTone } from "../ui/Badge";
import { EmptyState } from "../ui/EmptyState";

export function RiskFactorList({ assessment, documentId }: { assessment: RiskAssessment; documentId: string }) {
  if (assessment.factors.length === 0) {
    return (
      <EmptyState icon={ShieldCheck} title="No open risk factors" description="Every identified risk on this document has been mitigated or accepted." />
    );
  }

  return (
    <ul className="space-y-2">
      {assessment.factors.map((factor) => (
        <li key={factor.category}>
          <Link
            to={`/documents/${documentId}/risk`}
            className="flex items-center justify-between gap-3 rounded-md border border-line bg-paper-0 px-3.5 py-2.5 transition-colors hover:bg-paper-50"
          >
            <span className="text-sm text-text-primary">{factor.label}</span>
            <Badge tone={riskLevelTone(factor.topSeverity)}>{factor.topSeverity}</Badge>
          </Link>
        </li>
      ))}
    </ul>
  );
}
