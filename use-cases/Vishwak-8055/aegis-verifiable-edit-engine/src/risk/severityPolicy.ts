import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { severityRank, type Severity } from '../types/verification.js';

interface FindingPolicyEntry {
  severity: Severity;
  recoverable: boolean;
}

interface PolicyFile {
  defaultSeverity: Severity;
  defaultRecoverable: boolean;
  decisionThresholds: Record<Severity, string>;
  findings: Record<string, FindingPolicyEntry>;
  nonDowngradable: string[];
}

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_POLICY: PolicyFile = JSON.parse(readFileSync(path.join(moduleDir, 'policy.default.json'), 'utf-8'));

export interface PolicyOverride {
  findings?: Record<string, Partial<FindingPolicyEntry>>;
}

export interface RejectedOverride {
  kind: string;
  attemptedSeverity: Severity;
  enforcedSeverity: Severity;
  reason: string;
}

export interface VerificationPolicy {
  classify(kind: string): { severity: Severity; recoverable: boolean };
  decisionThresholds: Record<Severity, string>;
  /** Non-empty when the caller tried (via `policy` on the request) to weaken a finding kind that this policy marks non-downgradable. Always surfaced in the EditProof — see docs/SECURITY.md. */
  rejectedOverrides: RejectedOverride[];
}

/**
 * Builds the effective policy for one run. `override` can only ever make a
 * NON-nonDowngradable finding kind's severity/recoverability more specific;
 * any attempt to lower the severity of a kind listed in
 * `policy.default.json`'s `nonDowngradable` array is dropped and recorded in
 * `rejectedOverrides` rather than silently applied. This is what makes
 * "never weaken verification criteria simply to make an operation pass"
 * (brief section 13) an enforced property instead of a comment — see
 * test/adversarial/promptInjection.test.ts and
 * test/unit/severityPolicy.test.ts.
 */
export function loadPolicy(override?: PolicyOverride): VerificationPolicy {
  const merged: Record<string, FindingPolicyEntry> = { ...DEFAULT_POLICY.findings };
  const rejectedOverrides: RejectedOverride[] = [];

  if (override?.findings) {
    for (const [kind, patch] of Object.entries(override.findings)) {
      const base = merged[kind] ?? { severity: DEFAULT_POLICY.defaultSeverity, recoverable: DEFAULT_POLICY.defaultRecoverable };
      const attemptsDowngrade = patch.severity !== undefined && severityRank(patch.severity) < severityRank(base.severity);

      if (DEFAULT_POLICY.nonDowngradable.includes(kind) && attemptsDowngrade) {
        rejectedOverrides.push({
          kind,
          attemptedSeverity: patch.severity as Severity,
          enforcedSeverity: base.severity,
          reason: `"${kind}" is on the non-downgradable list; the requested override to ${patch.severity} was ignored.`,
        });
        continue;
      }
      merged[kind] = { ...base, ...patch };
    }
  }

  return {
    classify: (kind: string) => merged[kind] ?? { severity: DEFAULT_POLICY.defaultSeverity, recoverable: DEFAULT_POLICY.defaultRecoverable },
    decisionThresholds: DEFAULT_POLICY.decisionThresholds,
    rejectedOverrides,
  };
}
