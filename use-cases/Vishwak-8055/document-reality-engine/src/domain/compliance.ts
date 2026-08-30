import type { Requirement, RequirementCategory } from "../types/domain";
import { clampPercent } from "./utils";

export interface ComplianceCategoryBreakdown {
  category: RequirementCategory;
  total: number;
  satisfied: number;
  warnings: number;
  failures: number;
}

export interface ComplianceReport {
  total: number;
  satisfied: number;
  warnings: number;
  failures: number;
  /** % of requirements fully satisfied. Warnings and failures both withhold credit —
   *  a requirement either is met, or the document cannot claim it is. */
  scorePercent: number;
  byCategory: ComplianceCategoryBreakdown[];
}

const EMPTY_REPORT: ComplianceReport = {
  total: 0,
  satisfied: 0,
  warnings: 0,
  failures: 0,
  scorePercent: 100,
  byCategory: [],
};

export function computeCompliance(requirements: Requirement[]): ComplianceReport {
  const total = requirements.length;
  if (total === 0) return EMPTY_REPORT;

  const satisfied = requirements.filter((r) => r.status === "Satisfied").length;
  const warnings = requirements.filter((r) => r.status === "Warning").length;
  const failures = requirements.filter((r) => r.status === "Failed").length;

  const categories = Array.from(new Set(requirements.map((r) => r.category)));
  const byCategory: ComplianceCategoryBreakdown[] = categories
    .map((category) => {
      const inCategory = requirements.filter((r) => r.category === category);
      return {
        category,
        total: inCategory.length,
        satisfied: inCategory.filter((r) => r.status === "Satisfied").length,
        warnings: inCategory.filter((r) => r.status === "Warning").length,
        failures: inCategory.filter((r) => r.status === "Failed").length,
      };
    })
    .sort((a, b) => b.failures - a.failures || b.warnings - a.warnings);

  return {
    total,
    satisfied,
    warnings,
    failures,
    scorePercent: clampPercent((satisfied / total) * 100),
    byCategory,
  };
}

export function unresolvedRequirements(requirements: Requirement[]): Requirement[] {
  return requirements.filter((r) => r.status !== "Satisfied");
}
