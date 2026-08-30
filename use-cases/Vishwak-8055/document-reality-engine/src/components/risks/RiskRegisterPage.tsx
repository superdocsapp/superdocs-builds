import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import { ShieldCheck } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { RISK_LEVEL_ORDER } from "../../domain/risk";
import type { RiskStatus } from "../../types/domain";
import { formatDate } from "../../domain/utils";
import { RiskLevelBadge, RiskStatusBadge } from "../ui/Badge";
import { EmptyState } from "../ui/EmptyState";

const STATUS_OPTIONS = ["Open", "Mitigated", "Accepted", "All"] as const;
type StatusFilter = (typeof STATUS_OPTIONS)[number];

export function RiskRegisterPage() {
  const documents = useAppStore((s) => s.documents);
  const [status, setStatus] = useState<StatusFilter>("Open");

  const allRisks = useMemo(
    () => documents.flatMap((doc) => doc.risks.map((risk) => ({ risk, documentId: doc.id, documentTitle: doc.title }))),
    [documents],
  );

  const filtered = useMemo(() => {
    const scoped = status === "All" ? allRisks : allRisks.filter((entry) => entry.risk.status === (status as RiskStatus));
    return [...scoped].sort((a, b) => RISK_LEVEL_ORDER.indexOf(a.risk.severity) - RISK_LEVEL_ORDER.indexOf(b.risk.severity));
  }, [allRisks, status]);

  const openCount = allRisks.filter((entry) => entry.risk.status === "Open").length;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8 md:py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight text-text-primary">Risk Register</h1>
        <p className="mt-1 text-sm text-text-tertiary">{openCount} open findings across the workspace.</p>
      </div>

      <div className="mb-5 flex flex-wrap gap-1.5">
        {STATUS_OPTIONS.map((option) => (
          <button
            key={option}
            onClick={() => setStatus(option)}
            className={clsx(
              "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
              status === option ? "border-trust bg-trust-soft text-trust" : "border-line text-text-secondary hover:bg-paper-100",
            )}
          >
            {option}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon={ShieldCheck} title="No findings in this category" description="Try a different status filter." />
      ) : (
        <ul className="divide-y divide-line rounded-md border border-line bg-paper-0">
          {filtered.map(({ risk, documentId, documentTitle }) => (
            <li key={risk.id}>
              <Link
                to={`/documents/${documentId}/risk?risk=${risk.id}`}
                className="flex flex-col gap-2 px-5 py-4 transition-colors hover:bg-paper-50 sm:flex-row sm:items-start sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">{risk.title}</p>
                  <p className="mt-1 text-xs text-text-tertiary">
                    {documentTitle} · {risk.category} · detected {formatDate(risk.detectedAt)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <RiskLevelBadge level={risk.severity} />
                  <RiskStatusBadge status={risk.status} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
