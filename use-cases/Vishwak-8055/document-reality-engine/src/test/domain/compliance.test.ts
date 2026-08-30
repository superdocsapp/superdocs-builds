import { describe, expect, it } from "vitest";
import { computeCompliance, unresolvedRequirements } from "../../domain/compliance";
import type { Requirement } from "../../types/domain";
import { ironcladMsa } from "../../data/documents/ironcladMsa";
import { heliosNda } from "../../data/documents/heliosNda";

function req(overrides: Partial<Requirement>): Requirement {
  return {
    id: "req-x",
    documentId: "doc-x",
    category: "Metadata",
    description: "test requirement",
    status: "Satisfied",
    explanation: "because",
    severity: "Low",
    ...overrides,
  };
}

describe("computeCompliance", () => {
  it("returns a neutral report for a document with no requirements", () => {
    const report = computeCompliance([]);
    expect(report.total).toBe(0);
    expect(report.scorePercent).toBe(100);
    expect(report.byCategory).toEqual([]);
  });

  it("scores compliance as satisfied/total — warnings and failures both withhold credit", () => {
    const requirements = [
      req({ id: "r1", status: "Satisfied" }),
      req({ id: "r2", status: "Satisfied" }),
      req({ id: "r3", status: "Warning" }),
      req({ id: "r4", status: "Failed" }),
    ];
    const report = computeCompliance(requirements);
    expect(report.total).toBe(4);
    expect(report.satisfied).toBe(2);
    expect(report.warnings).toBe(1);
    expect(report.failures).toBe(1);
    expect(report.scorePercent).toBe(50);
  });

  it("breaks compliance down by category, worst categories first", () => {
    const requirements = [
      req({ id: "r1", category: "Policy", status: "Failed" }),
      req({ id: "r2", category: "Metadata", status: "Satisfied" }),
      req({ id: "r3", category: "Metadata", status: "Satisfied" }),
    ];
    const report = computeCompliance(requirements);
    expect(report.byCategory[0]?.category).toBe("Policy");
    expect(report.byCategory[0]?.failures).toBe(1);
  });

  it("matches the hand-authored flagship document: 10/15 satisfied", () => {
    const report = computeCompliance(ironcladMsa.requirements);
    expect(report.total).toBe(15);
    expect(report.satisfied).toBe(10);
    expect(report.warnings).toBe(2);
    expect(report.failures).toBe(3);
    expect(report.scorePercent).toBe(67);
  });

  it("scores a fully clean document at 100%", () => {
    const report = computeCompliance(heliosNda.requirements);
    expect(report.failures).toBe(0);
    expect(report.warnings).toBe(0);
    expect(report.scorePercent).toBe(100);
  });
});

describe("unresolvedRequirements", () => {
  it("excludes only Satisfied requirements", () => {
    const requirements = [req({ id: "r1", status: "Satisfied" }), req({ id: "r2", status: "Warning" }), req({ id: "r3", status: "Failed" })];
    expect(unresolvedRequirements(requirements).map((r) => r.id)).toEqual(["r2", "r3"]);
  });
});
