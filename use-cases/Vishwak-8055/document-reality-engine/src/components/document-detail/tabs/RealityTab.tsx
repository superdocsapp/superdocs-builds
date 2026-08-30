import { Link } from "react-router-dom";
import clsx from "clsx";
import { Info, ListTodo } from "lucide-react";
import type { SDDocument } from "../../../types/domain";
import { computeClaimsSummary } from "../../../domain/claims";
import { computeCompliance } from "../../../domain/compliance";
import { computeRisk } from "../../../domain/risk";
import { sortChangesByRecency, summarizeChange } from "../../../domain/changes";
import { formatDate } from "../../../domain/utils";
import { ProgressRing } from "../../ui/ProgressRing";
import { RiskLevelBadge } from "../../ui/Badge";
import { Tooltip } from "../../ui/Tooltip";
import { RiskFactorList } from "../RiskFactorList";

function scoreTone(value: number) {
  if (value >= 80) return "verified" as const;
  if (value >= 50) return "warning" as const;
  return "critical" as const;
}

function StatLabel({ label, explanation }: { label: string; explanation: string }) {
  return (
    <p className="flex items-center gap-1 text-xs font-medium text-text-tertiary">
      {label}
      <Tooltip label={explanation}>
        <Info className="h-3 w-3 cursor-help" aria-hidden="true" />
      </Tooltip>
    </p>
  );
}

export function RealityTab({ document }: { document: SDDocument }) {
  const claims = computeClaimsSummary(document.claims);
  const compliance = computeCompliance(document.requirements);
  const risk = computeRisk(document);
  const openActions = document.actions.filter((a) => a.status !== "Done");
  const latestChange = sortChangesByRecency(document.changes)[0];

  return (
    <div className="space-y-8">
      <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="flex flex-col items-center gap-2 rounded-md border border-line bg-paper-0 p-4">
          <ProgressRing value={claims.overallConfidence} tone={scoreTone(claims.overallConfidence)} />
          <StatLabel label="Confidence" explanation="Average confidence across every claim in this document, after verification." />
        </div>
        <div className="flex flex-col items-center gap-2 rounded-md border border-line bg-paper-0 p-4">
          <ProgressRing value={compliance.scorePercent} tone={scoreTone(compliance.scorePercent)} />
          <StatLabel label="Compliance" explanation="Share of requirements fully satisfied. Warnings and failures both withhold credit." />
        </div>
        <div className="flex flex-col items-center gap-2 rounded-md border border-line bg-paper-0 p-4">
          <ProgressRing value={claims.evidenceCoveragePercent} tone={scoreTone(claims.evidenceCoveragePercent)} />
          <StatLabel label="Evidence Coverage" explanation="Share of claims backed by at least one piece of linked evidence." />
        </div>
        <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-line bg-paper-0 p-4">
          <RiskLevelBadge level={risk.level} />
          <p className="font-numeric text-xs text-text-tertiary">Risk score {risk.score}</p>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 text-sm font-semibold text-text-primary">Why this risk level</h2>
          <RiskFactorList assessment={risk} documentId={document.id} />
        </div>

        <div className="space-y-6">
          <div>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-text-primary">Required actions</h2>
              <Link to={`/documents/${document.id}/reviews`} className="text-xs font-medium text-trust hover:underline">
                View all
              </Link>
            </div>
            {openActions.length === 0 ? (
              <p className="text-sm text-text-tertiary">No open actions on this document.</p>
            ) : (
              <ul className="space-y-2">
                {openActions.slice(0, 4).map((action) => (
                  <li key={action.id} className="flex items-start gap-2.5 rounded-md border border-line bg-paper-0 p-3">
                    <ListTodo className="mt-0.5 h-4 w-4 shrink-0 text-text-tertiary" aria-hidden="true" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-text-primary">{action.title}</p>
                      <p className="text-xs text-text-tertiary">
                        {action.assignee} · due {formatDate(action.dueDate)}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-text-primary">Most recent change</h2>
              <Link to={`/documents/${document.id}/changes`} className="text-xs font-medium text-trust hover:underline">
                View history
              </Link>
            </div>
            {!latestChange ? (
              <p className="text-sm text-text-tertiary">No changes recorded yet — this is the first version on file.</p>
            ) : (
              <div className="rounded-md border border-line bg-paper-0 p-3">
                <p className="font-numeric text-sm font-semibold text-text-primary">
                  v{latestChange.fromVersion} → v{latestChange.toVersion}
                </p>
                <p className="mt-1 text-xs text-text-tertiary">{latestChange.summary}</p>
                <ul className="mt-2.5 flex flex-wrap gap-1.5">
                  {summarizeChange(latestChange).map((line) => (
                    <li
                      key={line.label}
                      className={clsx(
                        "rounded-md border px-2 py-0.5 text-[11px] font-medium",
                        line.tone === "warning" && "border-warning/30 bg-warning-soft text-warning",
                        line.tone === "positive" && "border-verified/30 bg-verified-soft text-verified",
                        line.tone === "neutral" && "border-line bg-paper-50 text-text-secondary",
                      )}
                    >
                      {line.label}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
