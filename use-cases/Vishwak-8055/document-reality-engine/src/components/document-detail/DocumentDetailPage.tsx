import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, FileQuestion } from "lucide-react";
import { useDocument } from "../../store/appStore";
import { computeRisk } from "../../domain/risk";
import { unresolvedRequirements } from "../../domain/compliance";
import { unsupportedClaims } from "../../domain/claims";
import { formatCurrency, formatDate } from "../../domain/utils";
import { EmptyState } from "../ui/EmptyState";
import { Tabs, TabPanel } from "../ui/Tabs";
import { DocumentStatusBadge } from "../ui/Badge";
import { RealityTab } from "./tabs/RealityTab";
import { ClaimsEvidenceTab } from "./tabs/ClaimsEvidenceTab";
import { RequirementsTab } from "./tabs/RequirementsTab";
import { RiskTab } from "./tabs/RiskTab";
import { ChangesTab } from "./tabs/ChangesTab";
import { ReviewsTab } from "./tabs/ReviewsTab";
import { TimelineTab } from "./tabs/TimelineTab";

const VALID_TABS = ["reality", "claims", "requirements", "risk", "changes", "reviews", "timeline"] as const;
type TabId = (typeof VALID_TABS)[number];

function isValidTab(value: string | undefined): value is TabId {
  return Boolean(value) && (VALID_TABS as readonly string[]).includes(value as string);
}

function CountChip({ count, tone }: { count: number; tone: "critical" | "warning" }) {
  return (
    <span
      className={
        tone === "critical"
          ? "rounded-full bg-critical/15 px-1.5 py-0.5 text-[10px] font-semibold text-critical"
          : "rounded-full bg-warning/15 px-1.5 py-0.5 text-[10px] font-semibold text-warning"
      }
    >
      {count}
    </span>
  );
}

export function DocumentDetailPage() {
  const { documentId, tab } = useParams<{ documentId: string; tab?: string }>();
  const document = useDocument(documentId);
  const navigate = useNavigate();

  if (!document) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16">
        <EmptyState
          icon={FileQuestion}
          title="Document not found"
          description="This document may have been moved, renamed, or removed from the workspace."
          action={
            <Link to="/documents" className="mt-2 rounded-md bg-trust px-3.5 py-2 text-sm font-medium text-white transition-colors hover:bg-trust-strong">
              Back to Documents
            </Link>
          }
        />
      </div>
    );
  }

  const activeTab: TabId = isValidTab(tab) ? tab : "reality";
  const unsupportedCount = unsupportedClaims(document.claims).length;
  const unresolvedCount = unresolvedRequirements(document.requirements).length;
  const openRiskCount = computeRisk(document).openCount;

  const tabItems: { id: TabId; label: string; badge?: ReactNode }[] = [
    { id: "reality", label: "Reality" },
    { id: "claims", label: "Claims & Evidence", badge: unsupportedCount > 0 ? <CountChip count={unsupportedCount} tone="critical" /> : undefined },
    { id: "requirements", label: "Requirements", badge: unresolvedCount > 0 ? <CountChip count={unresolvedCount} tone="warning" /> : undefined },
    { id: "risk", label: "Risk", badge: openRiskCount > 0 ? <CountChip count={openRiskCount} tone="critical" /> : undefined },
    { id: "changes", label: "Changes" },
    { id: "reviews", label: "Reviews" },
    { id: "timeline", label: "Timeline" },
  ];

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">
      <Link to="/documents" className="mb-4 inline-flex items-center gap-1.5 text-sm text-text-tertiary transition-colors hover:text-text-primary">
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        Documents
      </Link>

      <header className="mb-6 flex flex-col gap-3 border-b border-line pb-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-text-tertiary">{document.type}</p>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-text-primary">{document.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-tertiary">
            <span>
              {document.owner.name} · {document.owner.role}
            </span>
            {document.counterparty && <span>Counterparty: {document.counterparty}</span>}
            {document.effectiveDate && <span>Effective {formatDate(document.effectiveDate)}</span>}
            {document.annualValue !== undefined && <span className="font-numeric">{formatCurrency(document.annualValue)}/yr</span>}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <DocumentStatusBadge status={document.status} />
          <span className="font-numeric rounded-md border border-line bg-paper-0 px-2 py-1 text-xs text-text-secondary">v{document.version}</span>
        </div>
      </header>

      <Tabs ariaLabel="Document sections" activeId={activeTab} onChange={(id) => navigate(`/documents/${document.id}/${id}`)} tabs={tabItems} />

      <div className="mt-6">
        <TabPanel id="reality" activeId={activeTab}>
          <RealityTab document={document} />
        </TabPanel>
        <TabPanel id="claims" activeId={activeTab}>
          <ClaimsEvidenceTab document={document} />
        </TabPanel>
        <TabPanel id="requirements" activeId={activeTab}>
          <RequirementsTab document={document} />
        </TabPanel>
        <TabPanel id="risk" activeId={activeTab}>
          <RiskTab document={document} />
        </TabPanel>
        <TabPanel id="changes" activeId={activeTab}>
          <ChangesTab document={document} />
        </TabPanel>
        <TabPanel id="reviews" activeId={activeTab}>
          <ReviewsTab document={document} />
        </TabPanel>
        <TabPanel id="timeline" activeId={activeTab}>
          <TimelineTab document={document} />
        </TabPanel>
      </div>
    </div>
  );
}
