import { describe, expect, it } from "vitest";
import { computeClaimsSummary, sortByVerificationSeverity, unsupportedClaims } from "../../domain/claims";
import type { Claim } from "../../types/domain";
import { ironcladMsa } from "../../data/documents/ironcladMsa";

function claim(overrides: Partial<Claim>): Claim {
  return {
    id: "claim-x",
    documentId: "doc-x",
    sectionId: "sec-x",
    text: "test claim",
    claimant: "Someone",
    evidenceIds: [],
    verificationStatus: "Unverified",
    confidence: 50,
    ...overrides,
  };
}

describe("computeClaimsSummary", () => {
  it("returns a neutral summary for zero claims", () => {
    const summary = computeClaimsSummary([]);
    expect(summary.total).toBe(0);
    expect(summary.overallConfidence).toBe(0);
    expect(summary.evidenceCoveragePercent).toBe(0);
  });

  it("tallies verification statuses and evidence coverage", () => {
    const claims = [
      claim({ id: "c1", verificationStatus: "Verified", confidence: 90, evidenceIds: ["e1"] }),
      claim({ id: "c2", verificationStatus: "Contradicted", confidence: 10, evidenceIds: ["e2"] }),
      claim({ id: "c3", verificationStatus: "Unverified", confidence: 40, evidenceIds: [] }),
      claim({ id: "c4", verificationStatus: "Needs Review", confidence: 50, evidenceIds: [] }),
    ];
    const summary = computeClaimsSummary(claims);
    expect(summary.total).toBe(4);
    expect(summary.verified).toBe(1);
    expect(summary.contradicted).toBe(1);
    expect(summary.unverified).toBe(1);
    expect(summary.needsReview).toBe(1);
    expect(summary.overallConfidence).toBe(48); // (90+10+40+50)/4 = 47.5 -> rounds to 48
    expect(summary.evidenceCoveragePercent).toBe(50); // 2 of 4 have evidence
  });

  it("matches the hand-authored flagship document's distribution across all five states", () => {
    const summary = computeClaimsSummary(ironcladMsa.claims);
    expect(summary.total).toBe(10);
    expect(summary.verified).toBe(3);
    expect(summary.partiallySupported).toBe(1);
    expect(summary.unverified).toBe(2);
    expect(summary.contradicted).toBe(2);
    expect(summary.needsReview).toBe(2);
    expect(summary.evidenceCoveragePercent).toBe(80); // 8 of 10 claims cite evidence
  });
});

describe("unsupportedClaims", () => {
  it("flags claims with no evidence, or that are unverified/contradicted even with evidence attached", () => {
    const result = unsupportedClaims(ironcladMsa.claims).map((c) => c.id).sort();
    expect(result).toEqual(["claim-ic-01", "claim-ic-03", "claim-ic-08", "claim-ic-09"].sort());
  });
});

describe("sortByVerificationSeverity", () => {
  it("orders Contradicted before Verified", () => {
    const claims = [claim({ id: "c1", verificationStatus: "Verified" }), claim({ id: "c2", verificationStatus: "Contradicted" })];
    expect(sortByVerificationSeverity(claims).map((c) => c.id)).toEqual(["c2", "c1"]);
  });
});
