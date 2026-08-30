import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import clsx from "clsx";
import { Sparkles } from "lucide-react";
import type { SDDocument } from "../../../types/domain";
import { computeRisk, sortByRiskSeverity } from "../../../domain/risk";
import { formatDate } from "../../../domain/utils";
import { useAppStore } from "../../../store/appStore";
import { mockIntelligenceServices } from "../../../services/intelligence/mock/mockIntelligenceServices";
import type { ReviewRecommendation } from "../../../services/intelligence/types";
import { RiskLevelBadge, RiskStatusBadge } from "../../ui/Badge";
import { RiskFactorList } from "../RiskFactorList";

export function RiskTab({ document }: { document: SDDocument }) {
  const [searchParams] = useSearchParams();
  const highlightId = searchParams.get("risk");
  const refs = useRef<Record<string, HTMLLIElement | null>>({});
  const resolveRisk = useAppStore((s) => s.resolveRisk);
  const [recommendations, setRecommendations] = useState<ReviewRecommendation[] | null>(null);

  const assessment = computeRisk(document);
  const risks = sortByRiskSeverity(document.risks);

  useEffect(() => {
    let cancelled = false;
    setRecommendations(null);
    mockIntelligenceServices.reviewRecommendation.recommend(document).then((result) => {
      if (!cancelled) setRecommendations(result);
    });
    return () => {
      cancelled = true;
    };
  }, [document]);

  useEffect(() => {
    if (highlightId) {
      refs.current[highlightId]?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [highlightId]);

  return (
    <div className="space-y-8">
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-paper-0 p-4">
        <div>
          <div className="flex items-center gap-2">
            <RiskLevelBadge level={assessment.level} />
            <span className="font-numeric text-xs text-text-tertiary">score {assessment.score}</span>
          </div>
          <p className="mt-1.5 text-xs text-text-tertiary">
            {assessment.openCount} open · {assessment.mitigatedCount} mitigated · {assessment.acceptedCount} accepted
          </p>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-text-primary">Why this risk level</h2>
        <RiskFactorList assessment={assessment} documentId={document.id} />
      </section>

      <section>
        <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-text-primary">
          <Sparkles className="h-4 w-4 text-trust" aria-hidden="true" />
          Recommended actions
        </h2>
        {!recommendations ? (
          <p className="text-sm text-text-tertiary">Analyzing…</p>
        ) : recommendations.length === 0 ? (
          <p className="text-sm text-text-tertiary">No recommendations — this document has no open risk factors or high-priority actions.</p>
        ) : (
          <ul className="space-y-2">
            {recommendations.map((rec) => (
              <li key={rec.id} className="rounded-md border border-line bg-paper-0 p-3">
                <p className="text-sm font-medium text-text-primary">{rec.title}</p>
                <p className="mt-0.5 text-xs text-text-tertiary">{rec.rationale}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-text-primary">All findings</h2>
        {risks.length === 0 ? (
          <p className="text-sm text-text-tertiary">No risks have been identified for this document.</p>
        ) : (
          <ul className="divide-y divide-line rounded-md border border-line bg-paper-0">
            {risks.map((risk) => (
              <li
                key={risk.id}
                ref={(el) => {
                  refs.current[risk.id] = el;
                }}
                className={clsx("px-4 py-3 transition-colors", highlightId === risk.id && "bg-trust-soft")}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-text-primary">{risk.title}</p>
                    <p className="mt-1 text-xs leading-relaxed text-text-tertiary">{risk.description}</p>
                    <p className="mt-1.5 text-[11px] text-text-tertiary">
                      Detected {formatDate(risk.detectedAt)} · {risk.category}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <RiskLevelBadge level={risk.severity} />
                    <RiskStatusBadge status={risk.status} />
                  </div>
                </div>
                {risk.status === "Open" && (
                  <button
                    onClick={() => resolveRisk(document.id, risk.id)}
                    className="mt-2.5 rounded-md border border-line px-2.5 py-1 text-xs font-medium text-text-secondary transition-colors hover:bg-paper-100"
                  >
                    Mark resolved
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
