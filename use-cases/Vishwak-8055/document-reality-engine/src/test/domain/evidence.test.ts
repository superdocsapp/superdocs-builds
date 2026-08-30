import { describe, expect, it } from "vitest";
import { evaluateStaleness, isEvidenceStale } from "../../domain/evidence";
import type { Evidence } from "../../types/domain";
import { DEMO_NOW } from "../../data/constants";
import { ironcladMsa } from "../../data/documents/ironcladMsa";

function evidence(overrides: Partial<Evidence>): Evidence {
  return {
    id: "ev-x",
    documentId: "doc-x",
    title: "test evidence",
    description: "because",
    sourceType: "Internal Data",
    sourceName: "Test Source",
    strength: "Strong",
    collectedAt: "2026-01-01T00:00:00.000Z",
    linkedClaimIds: [],
    ...overrides,
  };
}

function findEvidence(id: string): Evidence {
  const found = ironcladMsa.evidence.find((e) => e.id === id);
  if (!found) throw new Error(`fixture evidence ${id} not found`);
  return found;
}

describe("evaluateStaleness", () => {
  it("treats an explicit expiry date as authoritative", () => {
    const expired = evidence({ expiresAt: "2026-01-01T00:00:00.000Z" });
    const current = evidence({ expiresAt: "2027-01-01T00:00:00.000Z" });
    expect(evaluateStaleness(expired, DEMO_NOW).stale).toBe(true);
    expect(evaluateStaleness(current, DEMO_NOW).stale).toBe(false);
  });

  it("treats renewable evidence with no expiry date as stale after 12 months", () => {
    const old = evidence({ sourceType: "Certification", collectedAt: "2024-01-01T00:00:00.000Z" });
    const fresh = evidence({ sourceType: "Certification", collectedAt: "2026-06-01T00:00:00.000Z" });
    expect(isEvidenceStale(old, DEMO_NOW)).toBe(true);
    expect(isEvidenceStale(fresh, DEMO_NOW)).toBe(false);
  });

  it("does not apply the 12-month rule to non-renewable evidence types", () => {
    const old = evidence({ sourceType: "Internal Data", collectedAt: "2020-01-01T00:00:00.000Z" });
    expect(isEvidenceStale(old, DEMO_NOW)).toBe(false);
  });

  it("lets a reviewer override the computed result in either direction", () => {
    const wouldBeFresh = evidence({ sourceType: "Internal Data", collectedAt: "2026-08-01T00:00:00.000Z", reviewerOverride: "Stale" });
    const wouldBeStale = evidence({ sourceType: "Certification", collectedAt: "2020-01-01T00:00:00.000Z", reviewerOverride: "Fresh" });
    expect(isEvidenceStale(wouldBeFresh, DEMO_NOW)).toBe(true);
    expect(isEvidenceStale(wouldBeStale, DEMO_NOW)).toBe(false);
  });

  it("flags the flagship MSA's expired Certificate of Insurance as stale", () => {
    expect(isEvidenceStale(findEvidence("ev-ic-06"), DEMO_NOW)).toBe(true);
  });

  it("flags the flagship MSA's 14-month-old SOC 2 report as stale", () => {
    expect(isEvidenceStale(findEvidence("ev-ic-05"), DEMO_NOW)).toBe(true);
  });

  it("does not flag the flagship MSA's recent penetration test as stale", () => {
    expect(isEvidenceStale(findEvidence("ev-ic-04"), DEMO_NOW)).toBe(false);
  });
});
