import type { Claim, VerificationStatus } from "../types/domain";
import { clampPercent } from "./utils";

export interface ClaimsSummary {
  total: number;
  verified: number;
  partiallySupported: number;
  unverified: number;
  contradicted: number;
  needsReview: number;
  /** Mean of per-claim confidence, 0–100. */
  overallConfidence: number;
  /** % of claims that cite at least one piece of evidence. */
  evidenceCoveragePercent: number;
}

const EMPTY_SUMMARY: ClaimsSummary = {
  total: 0,
  verified: 0,
  partiallySupported: 0,
  unverified: 0,
  contradicted: 0,
  needsReview: 0,
  overallConfidence: 0,
  evidenceCoveragePercent: 0,
};

export function computeClaimsSummary(claims: Claim[]): ClaimsSummary {
  const total = claims.length;
  if (total === 0) return EMPTY_SUMMARY;

  const countByStatus = (status: VerificationStatus) => claims.filter((c) => c.verificationStatus === status).length;
  const withEvidence = claims.filter((c) => c.evidenceIds.length > 0).length;
  const confidenceSum = claims.reduce((sum, c) => sum + c.confidence, 0);

  return {
    total,
    verified: countByStatus("Verified"),
    partiallySupported: countByStatus("Partially Supported"),
    unverified: countByStatus("Unverified"),
    contradicted: countByStatus("Contradicted"),
    needsReview: countByStatus("Needs Review"),
    overallConfidence: clampPercent(confidenceSum / total),
    evidenceCoveragePercent: clampPercent((withEvidence / total) * 100),
  };
}

/** Claims that cannot currently be trusted at face value. */
export function unsupportedClaims(claims: Claim[]): Claim[] {
  return claims.filter(
    (c) => c.evidenceIds.length === 0 || c.verificationStatus === "Unverified" || c.verificationStatus === "Contradicted",
  );
}

export const VERIFICATION_ORDER: VerificationStatus[] = [
  "Contradicted",
  "Unverified",
  "Needs Review",
  "Partially Supported",
  "Verified",
];

export function sortByVerificationSeverity(claims: Claim[]): Claim[] {
  return [...claims].sort((a, b) => VERIFICATION_ORDER.indexOf(a.verificationStatus) - VERIFICATION_ORDER.indexOf(b.verificationStatus));
}
