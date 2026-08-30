import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import clsx from "clsx";
import { FileSearch } from "lucide-react";
import type { SDDocument, VerificationStatus } from "../../../types/domain";
import { sortByVerificationSeverity } from "../../../domain/claims";
import { VerificationDot } from "../../ui/VerificationDot";
import { EmptyState } from "../../ui/EmptyState";
import { ClaimDetailDrawer } from "../ClaimDetailDrawer";
import { DocumentReadingPane } from "../DocumentReadingPane";

const FILTERS = ["All", "Contradicted", "Unverified", "Needs Review", "Partially Supported", "Verified"] as const;
type Filter = (typeof FILTERS)[number];

export function ClaimsEvidenceTab({ document }: { document: SDDocument }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filter, setFilter] = useState<Filter>("All");
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);

  useEffect(() => {
    const claimParam = searchParams.get("claim");
    const evidenceParam = searchParams.get("evidence");
    if (claimParam) {
      setSelectedClaimId(claimParam);
    } else if (evidenceParam) {
      const owner = document.claims.find((c) => c.evidenceIds.includes(evidenceParam));
      if (owner) setSelectedClaimId(owner.id);
    }
  }, [searchParams, document]);

  const sorted = useMemo(() => sortByVerificationSeverity(document.claims), [document.claims]);
  const filtered = filter === "All" ? sorted : sorted.filter((c) => c.verificationStatus === (filter as VerificationStatus));
  const selectedClaim = document.claims.find((c) => c.id === selectedClaimId) ?? null;

  function closeDrawer() {
    setSelectedClaimId(null);
    if (searchParams.has("claim") || searchParams.has("evidence")) {
      const next = new URLSearchParams(searchParams);
      next.delete("claim");
      next.delete("evidence");
      setSearchParams(next, { replace: true });
    }
  }

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-5">
      <div className="lg:col-span-3">
        <h2 className="mb-3 text-sm font-semibold text-text-primary">Document</h2>
        <DocumentReadingPane document={document} onSelectClaim={setSelectedClaimId} />
      </div>

      <div className="lg:col-span-2">
        <h2 className="mb-3 text-sm font-semibold text-text-primary">Claims</h2>
        <div className="mb-3 flex flex-wrap gap-1.5">
          {FILTERS.map((option) => {
            const count = option === "All" ? document.claims.length : document.claims.filter((c) => c.verificationStatus === option).length;
            return (
              <button
                key={option}
                onClick={() => setFilter(option)}
                className={clsx(
                  "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                  filter === option ? "border-trust bg-trust-soft text-trust" : "border-line text-text-secondary hover:bg-paper-100",
                )}
              >
                {option} <span className="font-numeric">({count})</span>
              </button>
            );
          })}
        </div>

        {filtered.length === 0 ? (
          <EmptyState icon={FileSearch} title="No claims in this category" description="Try a different filter." />
        ) : (
          <ul className="divide-y divide-line rounded-md border border-line bg-paper-0">
            {filtered.map((claim) => (
              <li key={claim.id}>
                <button
                  onClick={() => setSelectedClaimId(claim.id)}
                  className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-paper-50"
                >
                  <VerificationDot status={claim.verificationStatus} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-text-primary">{claim.text}</p>
                    <p className="mt-1 text-xs text-text-tertiary">
                      {claim.claimant} · {claim.evidenceIds.length} evidence linked ·{" "}
                      <span className="font-numeric">{claim.confidence}%</span> confidence
                    </p>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <ClaimDetailDrawer document={document} claim={selectedClaim} onClose={closeDrawer} />
    </div>
  );
}
