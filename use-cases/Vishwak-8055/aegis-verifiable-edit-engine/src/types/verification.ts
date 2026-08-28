export type Severity = 'INFO' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export const SEVERITY_ORDER: Severity[] = ['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

export function severityRank(s: Severity): number {
  return SEVERITY_ORDER.indexOf(s);
}

export function maxSeverity(a: Severity, b: Severity): Severity {
  return severityRank(a) >= severityRank(b) ? a : b;
}

/** The six independent verification layers, matching docs/ARCHITECTURE.md. */
export type CheckerName = 'structural' | 'protected_value' | 'semantic' | 'scope' | 'formatting' | 'drift';

export interface FindingLocation {
  beforeBlockId?: string;
  afterBlockId?: string;
}

export interface Finding {
  /** Unique within a single verification run, e.g. "semantic:2". */
  id: string;
  checker: CheckerName;
  /**
   * A stable machine key, e.g. "SEMANTIC_OBLIGATION_TO_PERMISSION". This is
   * what src/risk/severityPolicy.ts maps to a Severity — checkers do NOT
   * decide their own severity, so severity policy stays centralized,
   * documented, and independently testable (see section 11 of the brief).
   */
  kind: string;
  confidence: number;
  message: string;
  before?: string;
  after?: string;
  location?: FindingLocation;
}

export interface CheckerOutcome {
  checker: CheckerName;
  findings: Finding[];
  /** Wall-clock duration, for the performance/observability review pass. */
  durationMs: number;
}

export interface ClassifiedFinding extends Finding {
  severity: Severity;
  recoverable: boolean;
}

export interface RiskAssessment {
  highestSeverity: Severity;
  counts: Record<Severity, number>;
  findings: ClassifiedFinding[];
}

export type Decision = 'VERIFIED' | 'VERIFIED_WITH_WARNINGS' | 'REQUIRES_REVIEW' | 'BLOCKED';
