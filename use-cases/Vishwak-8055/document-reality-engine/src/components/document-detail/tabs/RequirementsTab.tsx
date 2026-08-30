import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import clsx from "clsx";
import type { SDDocument } from "../../../types/domain";
import { computeCompliance } from "../../../domain/compliance";
import { groupBy } from "../../../domain/utils";
import { ProgressRing } from "../../ui/ProgressRing";
import { RequirementBadge } from "../../ui/Badge";

function scoreTone(value: number) {
  if (value >= 80) return "verified" as const;
  if (value >= 50) return "warning" as const;
  return "critical" as const;
}

export function RequirementsTab({ document }: { document: SDDocument }) {
  const [searchParams] = useSearchParams();
  const highlightId = searchParams.get("requirement");
  const refs = useRef<Record<string, HTMLLIElement | null>>({});

  const compliance = computeCompliance(document.requirements);
  const grouped = groupBy(document.requirements, (r) => r.category);

  useEffect(() => {
    if (highlightId) {
      refs.current[highlightId]?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [highlightId]);

  return (
    <div>
      <div className="mb-6 flex flex-col gap-4 rounded-md border border-line bg-paper-0 p-4 sm:flex-row sm:items-center">
        <ProgressRing value={compliance.scorePercent} tone={scoreTone(compliance.scorePercent)} size={72} />
        <div>
          <p className="text-sm font-semibold text-text-primary">Compliance</p>
          <p className="font-numeric mt-0.5 text-xs text-text-tertiary">
            {compliance.satisfied} satisfied · {compliance.warnings} warnings · {compliance.failures} failed · {compliance.total} total
          </p>
        </div>
      </div>

      <div className="space-y-6">
        {Object.entries(grouped).map(([category, requirements]) => (
          <div key={category}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-tertiary">{category}</h2>
            <ul className="divide-y divide-line rounded-md border border-line bg-paper-0">
              {requirements.map((requirement) => (
                <li
                  key={requirement.id}
                  ref={(el) => {
                    refs.current[requirement.id] = el;
                  }}
                  className={clsx("px-4 py-3 transition-colors", highlightId === requirement.id && "bg-trust-soft")}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-medium text-text-primary">{requirement.description}</p>
                    <RequirementBadge status={requirement.status} />
                  </div>
                  <p className="mt-1.5 text-xs leading-relaxed text-text-tertiary">{requirement.explanation}</p>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
