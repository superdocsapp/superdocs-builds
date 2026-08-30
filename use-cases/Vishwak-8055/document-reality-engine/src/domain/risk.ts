import type { Risk, RiskCategory, RiskLevel, SDDocument } from "../types/domain";
import { groupBy, pluralize } from "./utils";

/**
 * Severity weights used to roll individual, open risk records up into a
 * single document-level score. Weights double at each step (Low → Medium →
 * High) with Critical weighted higher still, so one Critical finding alone
 * cannot be silently diluted by a pile of Low ones, but also can't by
 * itself be the *only* thing that decides the document's fate.
 */
const SEVERITY_WEIGHT: Record<RiskLevel, number> = {
  Low: 1,
  Medium: 2,
  High: 3,
  Critical: 6,
};

/** Upper score bound (inclusive) for each level. First match wins, in order. */
const LEVEL_THRESHOLDS: { max: number; level: RiskLevel }[] = [
  { max: 4, level: "Low" },
  { max: 10, level: "Medium" },
  { max: 20, level: "High" },
  { max: Infinity, level: "Critical" },
];

const CATEGORY_NOUN: Record<RiskCategory, string> = {
  "Unsupported Claim": "unsupported claim",
  "Conflicting Statement": "conflicting statement",
  "Stale Evidence": "stale evidence source",
  "Missing Evidence": "missing evidence item",
  "Rule Violation": "rule violation",
  "Unresolved Review": "unresolved review",
  "High-Impact Change": "recent high-impact change",
  "Incomplete Approval": "incomplete approval",
};

export interface RiskFactor {
  category: RiskCategory;
  count: number;
  /** Highest severity within this category, for sorting/coloring the factor. */
  topSeverity: RiskLevel;
  label: string;
  riskIds: string[];
}

export interface RiskAssessment {
  level: RiskLevel;
  score: number;
  openCount: number;
  mitigatedCount: number;
  acceptedCount: number;
  factors: RiskFactor[];
}

function scoreToLevel(score: number): RiskLevel {
  const match = LEVEL_THRESHOLDS.find((t) => score <= t.max);
  return match ? match.level : "Critical";
}

const SEVERITY_RANK: Record<RiskLevel, number> = { Low: 0, Medium: 1, High: 2, Critical: 3 };

export function computeRisk(document: Pick<SDDocument, "risks">): RiskAssessment {
  const openRisks = document.risks.filter((r) => r.status === "Open");
  const score = openRisks.reduce((sum, r) => sum + SEVERITY_WEIGHT[r.severity], 0);
  const level = scoreToLevel(score);

  const grouped = groupBy(openRisks, (r) => r.category);
  const factors: RiskFactor[] = Object.entries(grouped)
    .map(([category, risks]) => {
      const typedRisks = risks as Risk[];
      const topSeverity = typedRisks.reduce<RiskLevel>(
        (top, r) => (SEVERITY_RANK[r.severity] > SEVERITY_RANK[top] ? r.severity : top),
        "Low",
      );
      return {
        category: category as RiskCategory,
        count: typedRisks.length,
        topSeverity,
        label: `${typedRisks.length} ${pluralize(typedRisks.length, CATEGORY_NOUN[category as RiskCategory])}`,
        riskIds: typedRisks.map((r) => r.id),
      };
    })
    .sort((a, b) => SEVERITY_RANK[b.topSeverity] - SEVERITY_RANK[a.topSeverity] || b.count - a.count);

  return {
    level,
    score,
    openCount: openRisks.length,
    mitigatedCount: document.risks.filter((r) => r.status === "Mitigated").length,
    acceptedCount: document.risks.filter((r) => r.status === "Accepted").length,
    factors,
  };
}

export const RISK_LEVEL_ORDER: RiskLevel[] = ["Critical", "High", "Medium", "Low"];

export function sortByRiskSeverity(risks: Risk[]): Risk[] {
  return [...risks].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]);
}
