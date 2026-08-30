import type { RiskLevel, SDDocument } from "../types/domain";
import { DEMO_NOW } from "../data/constants";
import { computeClaimsSummary } from "./claims";
import { computeCompliance } from "./compliance";
import { computeRisk } from "./risk";
import { isEvidenceStale } from "./evidence";
import { daysBetween } from "./utils";

export type AttentionKind = "Open Risk" | "Stale Evidence" | "Failed Requirement" | "Pending Approval" | "High-Impact Change";

export interface AttentionItem {
  id: string;
  documentId: string;
  documentTitle: string;
  kind: AttentionKind;
  title: string;
  detail: string;
  severity: RiskLevel;
  navigateTo: string;
  timestamp: string;
}

const SEVERITY_RANK: Record<RiskLevel, number> = { Critical: 3, High: 2, Medium: 1, Low: 0 };
const RECENT_CHANGE_WINDOW_DAYS = 21;

export function computeAttentionItems(documents: SDDocument[], nowIso: string = DEMO_NOW): AttentionItem[] {
  const items: AttentionItem[] = [];

  for (const doc of documents) {
    const risk = computeRisk(doc);

    for (const r of doc.risks.filter((r) => r.status === "Open" && (r.severity === "Critical" || r.severity === "High"))) {
      items.push({
        id: r.id,
        documentId: doc.id,
        documentTitle: doc.title,
        kind: "Open Risk",
        title: r.title,
        detail: r.description,
        severity: r.severity,
        navigateTo: `/documents/${doc.id}/risk?risk=${r.id}`,
        timestamp: r.detectedAt,
      });
    }

    for (const e of doc.evidence) {
      if (isEvidenceStale(e, nowIso)) {
        items.push({
          id: e.id,
          documentId: doc.id,
          documentTitle: doc.title,
          kind: "Stale Evidence",
          title: e.title,
          detail: `${e.sourceType} from ${e.sourceName} is due for renewal.`,
          severity: "Medium",
          navigateTo: `/documents/${doc.id}/claims?evidence=${e.id}`,
          timestamp: e.collectedAt,
        });
      }
    }

    for (const req of doc.requirements.filter((r) => r.status === "Failed")) {
      items.push({
        id: req.id,
        documentId: doc.id,
        documentTitle: doc.title,
        kind: "Failed Requirement",
        title: req.description,
        detail: req.explanation,
        severity: req.severity === "High" ? "High" : req.severity === "Medium" ? "Medium" : "Low",
        navigateTo: `/documents/${doc.id}/requirements?requirement=${req.id}`,
        timestamp: doc.updatedAt,
      });
    }

    const lastRequested = [...doc.reviewEvents].reverse().find((ev) => ev.type === "Approval Requested");
    const lastGranted = [...doc.reviewEvents].reverse().find((ev) => ev.type === "Approval Granted");
    if (
      doc.status === "In Review" &&
      lastRequested &&
      (!lastGranted || new Date(lastGranted.timestamp).getTime() < new Date(lastRequested.timestamp).getTime())
    ) {
      items.push({
        id: `approval-${doc.id}`,
        documentId: doc.id,
        documentTitle: doc.title,
        kind: "Pending Approval",
        title: `Approval outstanding on ${doc.title}`,
        detail: lastRequested.explanation,
        severity: risk.level === "Critical" || risk.level === "High" ? risk.level : "Medium",
        navigateTo: `/documents/${doc.id}/reviews`,
        timestamp: lastRequested.timestamp,
      });
    }

    const mostRecentChange = [...doc.changes].sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime())[0];
    if (mostRecentChange && mostRecentChange.riskDelta > 0 && daysBetween(mostRecentChange.occurredAt, nowIso) <= RECENT_CHANGE_WINDOW_DAYS) {
      items.push({
        id: mostRecentChange.id,
        documentId: doc.id,
        documentTitle: doc.title,
        kind: "High-Impact Change",
        title: `v${mostRecentChange.fromVersion} → v${mostRecentChange.toVersion} increased risk`,
        detail: mostRecentChange.summary,
        severity: "High",
        navigateTo: `/documents/${doc.id}/changes`,
        timestamp: mostRecentChange.occurredAt,
      });
    }
  }

  return items.sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
}

export interface DashboardMetrics {
  totalDocuments: number;
  totalClaims: number;
  verifiedClaims: number;
  avgEvidenceCoveragePercent: number;
  avgCompliancePercent: number;
  openRisks: number;
  documentsAtHighOrCriticalRisk: number;
  pendingReviews: number;
  recentChanges: number;
  openActions: number;
}

export function computeDashboardMetrics(documents: SDDocument[], nowIso: string = DEMO_NOW): DashboardMetrics {
  const n = documents.length || 1;
  let totalClaims = 0;
  let verifiedClaims = 0;
  let coverageSum = 0;
  let complianceSum = 0;
  let openRisks = 0;
  let atRiskDocs = 0;
  let pendingReviews = 0;
  let recentChanges = 0;
  let openActions = 0;

  for (const doc of documents) {
    const claimsSummary = computeClaimsSummary(doc.claims);
    totalClaims += claimsSummary.total;
    verifiedClaims += claimsSummary.verified;
    coverageSum += claimsSummary.evidenceCoveragePercent;
    complianceSum += computeCompliance(doc.requirements).scorePercent;
    openRisks += doc.risks.filter((r) => r.status === "Open").length;
    if (["High", "Critical"].includes(computeRisk(doc).level)) atRiskDocs += 1;
    if (doc.status === "In Review") pendingReviews += 1;
    recentChanges += doc.changes.filter((c) => daysBetween(c.occurredAt, nowIso) <= RECENT_CHANGE_WINDOW_DAYS).length;
    openActions += doc.actions.filter((a) => a.status !== "Done").length;
  }

  return {
    totalDocuments: documents.length,
    totalClaims,
    verifiedClaims,
    avgEvidenceCoveragePercent: Math.round(coverageSum / n),
    avgCompliancePercent: Math.round(complianceSum / n),
    openRisks,
    documentsAtHighOrCriticalRisk: atRiskDocs,
    pendingReviews,
    recentChanges,
    openActions,
  };
}
