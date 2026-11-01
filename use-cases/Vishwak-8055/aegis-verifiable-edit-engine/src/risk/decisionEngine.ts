import type { ClassifiedFinding, Decision, Finding, RiskAssessment, Severity } from '../types/verification.js';
import { maxSeverity } from '../types/verification.js';
import type { VerificationPolicy } from './severityPolicy.js';

export function classifyFindings(findings: Finding[], policy: VerificationPolicy): ClassifiedFinding[] {
  return findings.map((finding) => {
    const { severity, recoverable } = policy.classify(finding.kind);
    return { ...finding, severity, recoverable };
  });
}

export function assessRisk(classified: ClassifiedFinding[]): RiskAssessment {
  const counts: Record<Severity, number> = { INFO: 0, LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 };
  let highestSeverity: Severity = 'INFO';
  for (const finding of classified) {
    counts[finding.severity]++;
    highestSeverity = maxSeverity(highestSeverity, finding.severity);
  }
  return { highestSeverity, counts, findings: classified };
}

/**
 * The system must never silently treat a failed verification as success
 * (brief section 12) — this function is the single place that maps risk to
 * a decision, so that guarantee has exactly one implementation to audit.
 */
export function decide(risk: RiskAssessment, policy: VerificationPolicy): Decision {
  const mapped = policy.decisionThresholds[risk.highestSeverity];
  if (mapped === 'VERIFIED' || mapped === 'VERIFIED_WITH_WARNINGS' || mapped === 'REQUIRES_REVIEW' || mapped === 'BLOCKED') {
    return mapped;
  }
  // An unrecognized/misconfigured threshold must fail closed, never open.
  return 'REQUIRES_REVIEW';
}
