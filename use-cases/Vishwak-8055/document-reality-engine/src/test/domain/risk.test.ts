import { describe, expect, it } from "vitest";
import { computeRisk } from "../../domain/risk";
import type { Risk } from "../../types/domain";
import { ironcladMsa } from "../../data/documents/ironcladMsa";
import { meridianVsq } from "../../data/documents/meridianVsq";
import { coastalBridgeLetter } from "../../data/documents/coastalBridgeLetter";
import { remoteWorkPolicy } from "../../data/documents/remoteWorkPolicy";
import { heliosNda } from "../../data/documents/heliosNda";
import { brightpathDpa } from "../../data/documents/brightpathDpa";

function risk(overrides: Partial<Risk>): Risk {
  return {
    id: "risk-x",
    documentId: "doc-x",
    category: "Unsupported Claim",
    title: "test risk",
    description: "because",
    severity: "Low",
    status: "Open",
    detectedAt: "2026-01-01T00:00:00.000Z",
    relatedClaimIds: [],
    relatedRequirementIds: [],
    relatedEvidenceIds: [],
    ...overrides,
  };
}

describe("computeRisk", () => {
  it("returns Low with a zero score when there are no risks", () => {
    const assessment = computeRisk({ risks: [] });
    expect(assessment.score).toBe(0);
    expect(assessment.level).toBe("Low");
    expect(assessment.factors).toEqual([]);
  });

  it("ignores Mitigated and Accepted risks when scoring", () => {
    const assessment = computeRisk({
      risks: [risk({ id: "r1", severity: "Critical", status: "Mitigated" }), risk({ id: "r2", severity: "Critical", status: "Accepted" })],
    });
    expect(assessment.score).toBe(0);
    expect(assessment.level).toBe("Low");
    expect(assessment.mitigatedCount).toBe(1);
    expect(assessment.acceptedCount).toBe(1);
  });

  it("classifies severity bands: Low, Medium, High, Critical", () => {
    const many = (severity: Risk["severity"], count: number) => Array.from({ length: count }, (_, i) => risk({ id: `r${i}`, severity }));
    expect(computeRisk({ risks: many("Low", 1) }).level).toBe("Low"); // score 1
    expect(computeRisk({ risks: many("Medium", 3) }).level).toBe("Medium"); // score 6
    expect(computeRisk({ risks: many("High", 4) }).level).toBe("High"); // score 12
    expect(computeRisk({ risks: many("Critical", 4) }).level).toBe("Critical"); // score 24
  });

  it("groups open risks into explainable factors sorted by severity", () => {
    const assessment = computeRisk({
      risks: [
        risk({ id: "r1", category: "Stale Evidence", severity: "Medium" }),
        risk({ id: "r2", category: "Stale Evidence", severity: "Medium" }),
        risk({ id: "r3", category: "Missing Evidence", severity: "High" }),
      ],
    });
    expect(assessment.factors[0]?.category).toBe("Missing Evidence");
    expect(assessment.factors[1]?.category).toBe("Stale Evidence");
    expect(assessment.factors[1]?.count).toBe(2);
    expect(assessment.factors[1]?.label).toBe("2 stale evidence sources");
  });

  describe("against the seed workspace", () => {
    it("flags the flagship MSA as High risk (score 20 from 4 High + 4 Medium open findings)", () => {
      const assessment = computeRisk(ironcladMsa);
      expect(assessment.openCount).toBe(8);
      expect(assessment.score).toBe(20);
      expect(assessment.level).toBe("High");
    });

    it("flags the rejected vendor questionnaire as Critical risk", () => {
      const assessment = computeRisk(meridianVsq);
      expect(assessment.score).toBe(21);
      expect(assessment.level).toBe("Critical");
    });

    it("flags the unsigned bridge letter as Medium risk", () => {
      expect(computeRisk(coastalBridgeLetter).level).toBe("Medium");
    });

    it("flags the published policy as Low risk", () => {
      expect(computeRisk(remoteWorkPolicy).level).toBe("Low");
    });

    it("flags fully clean documents as Low risk with a zero score", () => {
      expect(computeRisk(heliosNda).score).toBe(0);
      expect(computeRisk(heliosNda).level).toBe("Low");
    });

    it("does not let a resolved historical finding inflate a clean document's risk", () => {
      const assessment = computeRisk(brightpathDpa);
      expect(assessment.openCount).toBe(0);
      expect(assessment.mitigatedCount).toBe(1);
      expect(assessment.level).toBe("Low");
    });
  });
});
