import { useMemo } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, ClipboardCheck, FileText, GitBranch, ListChecks, ListTodo, ShieldAlert, Stamp } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { computeAttentionItems, computeDashboardMetrics } from "../../domain/attention";
import { computeRisk } from "../../domain/risk";
import { formatDateTime } from "../../domain/utils";
import { MetricCard } from "./MetricCard";
import { AttentionList } from "./AttentionList";
import { DocumentStatusBadge, RiskLevelBadge } from "../ui/Badge";

export function Dashboard() {
  const documents = useAppStore((s) => s.documents);
  const metrics = useMemo(() => computeDashboardMetrics(documents), [documents]);
  const attentionItems = useMemo(() => computeAttentionItems(documents), [documents]);

  const recentDecisions = useMemo(
    () =>
      documents
        .flatMap((doc) => doc.decisions.map((decision) => ({ decision, documentTitle: doc.title, documentId: doc.id })))
        .sort((a, b) => new Date(b.decision.decidedAt).getTime() - new Date(a.decision.decidedAt).getTime())
        .slice(0, 5),
    [documents],
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight text-text-primary">Dashboard</h1>
        <p className="mt-1 text-sm text-text-tertiary">What needs your attention across {documents.length} documents.</p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard label="Documents" value={String(metrics.totalDocuments)} icon={FileText} />
        <MetricCard label="Verified Claims" value={`${metrics.verifiedClaims}/${metrics.totalClaims}`} icon={CheckCircle2} />
        <MetricCard label="Evidence Coverage" value={`${metrics.avgEvidenceCoveragePercent}%`} icon={Stamp} />
        <MetricCard label="Compliance" value={`${metrics.avgCompliancePercent}%`} icon={ListChecks} />
        <MetricCard label="Open Risks" value={String(metrics.openRisks)} icon={ShieldAlert} />
        <MetricCard label="Pending Reviews" value={String(metrics.pendingReviews)} icon={ClipboardCheck} />
        <MetricCard label="Recent Changes" value={String(metrics.recentChanges)} icon={GitBranch} />
        <MetricCard label="Open Actions" value={String(metrics.openActions)} icon={ListTodo} />
      </div>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section className="lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold text-text-primary">Needs your attention</h2>
          <AttentionList items={attentionItems} />
        </section>

        <div className="space-y-6">
          <section>
            <h2 className="mb-3 text-sm font-semibold text-text-primary">Documents at a glance</h2>
            <ul className="divide-y divide-line rounded-md border border-line bg-paper-0">
              {documents.map((doc) => {
                const risk = computeRisk(doc);
                return (
                  <li key={doc.id}>
                    <Link to={`/documents/${doc.id}`} className="flex items-center justify-between gap-2 px-4 py-3 transition-colors hover:bg-paper-50">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-text-primary">{doc.title}</p>
                        <div className="mt-1.5">
                          <DocumentStatusBadge status={doc.status} />
                        </div>
                      </div>
                      <RiskLevelBadge level={risk.level} />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-text-primary">Recent decisions</h2>
            {recentDecisions.length === 0 ? (
              <p className="text-sm text-text-tertiary">No decisions recorded yet.</p>
            ) : (
              <ul className="space-y-2">
                {recentDecisions.map(({ decision, documentTitle, documentId }) => (
                  <li key={decision.id} className="rounded-md border border-line bg-paper-0 p-3">
                    <Link to={`/documents/${documentId}/reviews`} className="block">
                      <p className="text-sm font-medium text-text-primary">{decision.description}</p>
                      <p className="mt-1 text-xs text-text-tertiary">
                        {decision.outcome} by {decision.decidedBy} · {formatDateTime(decision.decidedAt)}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-text-tertiary">{documentTitle}</p>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
