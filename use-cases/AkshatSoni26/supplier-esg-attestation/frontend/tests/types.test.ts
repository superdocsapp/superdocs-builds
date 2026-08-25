import { describe, it, expect } from "bun:test";
import { Supplier, Assessment, Finding } from "../app/types";

describe("Frontend Type Model & Integrity Tests", () => {
  it("Supplier structure satisfies type requirements", () => {
    const supplier: Supplier = {
      id: "sup-002-apex",
      name: "Apex Electronics Manufacturing Ltd.",
      code: "SUP-APEX-02",
      tier: "TIER_2_MANUFACTURING",
      region: "APAC",
      country: "Taiwan",
      primary_contact_email: "esg-office@apex-semi.tw",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    expect(supplier.id).toBe("sup-002-apex");
    expect(supplier.tier).toBe("TIER_2_MANUFACTURING");
    expect(supplier.region).toBe("APAC");
  });

  it("Assessment model supports findings collection", () => {
    const finding: Finding = {
      id: "find-001",
      pillar: "SOCIAL",
      severity: "CRITICAL",
      standard_clause: "Clause 2.3: Maximum Statutory Working Hours",
      shortfall_summary: "Working hours of 72 hrs/week exceed ILO limit.",
      supplier_exact_quote: "Workers operate up to 72 hours per week.",
      source_location: "Labor Disclosure",
      recommended_action: "Cap weekly hours at 60.",
      review_decision: "PENDING",
    };

    const assessment: Assessment = {
      id: "ass-001",
      attestation_id: "att-001",
      overall_risk_score: 85.0,
      risk_tier: "CRITICAL",
      environmental_score: 75.0,
      social_score: 35.0,
      governance_score: 90.0,
      summary_markdown: "Critical findings identified",
      is_approved: false,
      findings: [finding],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    expect(assessment.findings).toHaveLength(1);
    expect(assessment.findings[0].severity).toBe("CRITICAL");
    expect(assessment.findings[0].review_decision).toBe("PENDING");
  });
});
