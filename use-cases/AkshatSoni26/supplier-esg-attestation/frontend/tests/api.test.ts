import { describe, it, expect, mock, beforeEach } from "bun:test";
import { api } from "../app/services/api";

describe("Frontend API Service Unit Tests", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("getSuppliers makes GET request to /api/v1/suppliers", async () => {
    const mockSuppliers = [
      {
        id: "sup-001-acme",
        name: "Acme Precision Components GmbH",
        code: "SUP-ACME-01",
        tier: "TIER_1_STRATEGIC",
        region: "EU",
        country: "Germany",
        primary_contact_email: "compliance@acme-precision.de",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ];

    globalThis.fetch = mock(async (url: any) => {
      expect(url.toString()).toContain("/api/v1/suppliers");
      return new Response(JSON.stringify(mockSuppliers), { status: 200 });
    }) as any;

    const result = await api.getSuppliers();
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("Acme Precision Components GmbH");
    expect(result[0].tier).toBe("TIER_1_STRATEGIC");
  });

  it("issueQuestionnaire sends correct payload to /api/v1/issuance/issue", async () => {
    const mockResponse = {
      attestation_id: "att-acme-2026",
      supplier_id: "sup-001-acme",
      supplier_name: "Acme Precision Components GmbH",
      tier: "TIER_1_STRATEGIC",
      region: "EU",
      cycle_year: 2026,
      status: "ISSUED",
      document_title: "ESG Attestation - Acme",
      document_content_markdown: "# Code of Conduct",
      included_annexes: ["tier1", "EU CSRD"],
      superdocs_document_id: "sd-doc-12345",
      export_url: "/api/v1/superdocs/download/sd-doc-12345.pdf",
    };

    globalThis.fetch = mock(async (url: any, opts: any) => {
      expect(url.toString()).toContain("/api/v1/issuance/issue");
      expect(opts.method).toBe("POST");
      const body = JSON.parse(opts.body);
      expect(body.supplier_id).toBe("sup-001-acme");
      expect(body.cycle_year).toBe(2026);
      return new Response(JSON.stringify(mockResponse), { status: 200 });
    }) as any;

    const result = await api.issueQuestionnaire("sup-001-acme", 2026);

    expect(result.attestation_id).toBe("att-acme-2026");
    expect(result.status).toBe("ISSUED");
  });

  it("submitReview sends decision to review endpoint", async () => {
    const mockResponse = {
      id: "ass-123",
      attestation_id: "att-123",
      overall_risk_score: 25.0,
      risk_tier: "LOW",
      environmental_score: 90.0,
      social_score: 95.0,
      governance_score: 85.0,
      summary_markdown: "Approved",
      is_approved: true,
      findings: [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    globalThis.fetch = mock(async (url: any, opts: any) => {
      expect(url.toString()).toContain("/api/v1/review/ass-123/submit");
      expect(opts.method).toBe("POST");
      const body = JSON.parse(opts.body);
      expect(body.is_approved).toBe(true);
      expect(body.approved_by).toBe("Chief Compliance Officer");
      return new Response(JSON.stringify(mockResponse), { status: 200 });
    }) as any;

    const result = await api.submitReview(
      "ass-123",
      true,
      "Chief Compliance Officer",
      [{ finding_id: "find-1", review_decision: "ACCEPTED" }]
    );

    expect(result.is_approved).toBe(true);
  });

  it("getProgrammeReport fetches 2026 programme metrics", async () => {
    const mockReport = {
      cycle_year: 2026,
      total_suppliers_invited: 3,
      responses_submitted: 2,
      attestation_rate_pct: 66.7,
      overall_programme_risk_level: "MEDIUM",
      pillar_averages: {
        environmental_avg: 80.0,
        social_avg: 75.0,
        governance_avg: 90.0,
        overall_compliance_avg: 81.7,
      },
      risk_tier_breakdown: [],
      tier_distribution: [],
      regional_distribution: [],
      top_recurring_shortfalls: [],
      executive_narrative_markdown: "# Executive Summary",
      generated_at: new Date().toISOString(),
    };

    globalThis.fetch = mock(async (url: any) => {
      expect(url.toString()).toContain("/api/v1/reports/programme-summary?cycle_year=2026");
      return new Response(JSON.stringify(mockReport), { status: 200 });
    }) as any;

    const result = await api.getProgrammeReport(2026);
    expect(result.cycle_year).toBe(2026);
    expect(result.attestation_rate_pct).toBe(66.7);
  });

  it("generateFollowUpLetter posts to follow-ups endpoint", async () => {
    const mockLetter = {
      id: "let-123",
      attestation_id: "att-123",
      recipient_email: "supplier@corp.com",
      subject: "[ACTION REQUIRED] Remediation Notice",
      content_markdown: "# Notice",
      status: "DRAFT",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    globalThis.fetch = mock(async (url: any, opts: any) => {
      expect(url.toString()).toContain("/api/v1/follow-ups/generate");
      expect(opts.method).toBe("POST");
      const body = JSON.parse(opts.body);
      expect(body.attestation_id).toBe("att-123");
      expect(body.custom_remediation_deadline_days).toBe(30);
      return new Response(JSON.stringify(mockLetter), { status: 200 });
    }) as any;

    const result = await api.generateFollowUpLetter("att-123", 30);
    expect(result.id).toBe("let-123");
    expect(result.status).toBe("DRAFT");
  });
});
