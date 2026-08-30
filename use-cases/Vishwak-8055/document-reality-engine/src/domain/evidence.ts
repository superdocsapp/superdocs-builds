import type { Evidence, EvidenceSourceType } from "../types/domain";
import { DEMO_NOW } from "../data/constants";

/**
 * Source types that carry a natural renewal cycle. If no explicit
 * `expiresAt` is on file, we treat evidence of these types as stale once
 * it is more than a year old — a SOC 2 report or insurance certificate
 * from 18 months ago is not "current" just because no one set a date.
 */
const RENEWABLE_SOURCE_TYPES: EvidenceSourceType[] = ["Certification", "Audit Report", "Attestation"];
const IMPLICIT_STALE_AFTER_MS = 365 * 24 * 60 * 60 * 1000;

export interface StalenessResult {
  stale: boolean;
  reason: string | null;
}

/**
 * Determines whether a piece of evidence is stale as of `nowIso`.
 * Defaults to the fixed demo clock so results are deterministic; callers
 * that want "as of right now" can pass `new Date().toISOString()` explicitly.
 */
export function evaluateStaleness(evidence: Evidence, nowIso: string = DEMO_NOW): StalenessResult {
  if (evidence.reviewerOverride === "Stale") {
    return { stale: true, reason: "Flagged stale by a reviewer" };
  }
  if (evidence.reviewerOverride === "Fresh") {
    return { stale: false, reason: null };
  }

  const now = new Date(nowIso).getTime();

  if (evidence.expiresAt) {
    const expires = new Date(evidence.expiresAt).getTime();
    if (now > expires) {
      return { stale: true, reason: `Expired ${formatAgeDays(now - expires)} ago` };
    }
    return { stale: false, reason: null };
  }

  if (RENEWABLE_SOURCE_TYPES.includes(evidence.sourceType)) {
    const age = now - new Date(evidence.collectedAt).getTime();
    if (age > IMPLICIT_STALE_AFTER_MS) {
      return {
        stale: true,
        reason: `${evidence.sourceType} is ${formatAgeDays(age)} old; no renewal on file (12-month policy)`,
      };
    }
  }

  return { stale: false, reason: null };
}

export function isEvidenceStale(evidence: Evidence, nowIso: string = DEMO_NOW): boolean {
  return evaluateStaleness(evidence, nowIso).stale;
}

function formatAgeDays(ms: number): string {
  const days = Math.round(ms / (24 * 60 * 60 * 1000));
  if (days < 30) return `${days}d`;
  const months = Math.round(days / 30);
  if (months < 24) return `${months}mo`;
  return `${Math.round(months / 12)}y`;
}
