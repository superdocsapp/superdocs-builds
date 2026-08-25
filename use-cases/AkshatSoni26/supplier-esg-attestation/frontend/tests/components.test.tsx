import { describe, it, expect } from "bun:test";
import React from "react";
import { renderToString } from "react-dom/server";
import { StatCard } from "../app/components/StatCard";
import { BackendOfflineAlert } from "../app/components/BackendOfflineAlert";
import { HeroBanner } from "../app/components/HeroBanner";
import { KpiStatsSection } from "../app/components/KpiStatsSection";
import { SupplierDirectoryTable } from "../app/components/SupplierDirectoryTable";
import { Navbar } from "../app/components/Navbar";
import { ComplianceAuditHub } from "../app/components/ComplianceAuditHub";
import { ShieldCheck } from "lucide-react";
import { ProgrammeReport, Supplier, AttestationCycle, Assessment } from "../app/types";

describe("Frontend Component SSR Rendering Tests", () => {
  const mockSuppliers: Supplier[] = [
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

  it("Navbar renders brand, 3 tabs, and actions", () => {
    const html = renderToString(
      <Navbar
        onRefresh={() => {}}
        onOpenReport={() => {}}
        loading={false}
        activeTab="operations"
        setActiveTab={() => {}}
      />
    );

    expect(html).toContain("SuperDocs");
    expect(html).toContain("ESG Attestation Engine");
    expect(html).toContain("Supplier Operations");
    expect(html).toContain("Executive Analytics");
    expect(html).toContain("Compliance &amp; Audit Hub");
    expect(html).toContain("Executive Report");
  });

  it("ComplianceAuditHub renders evidence repository and statistics", () => {
    const mockCycle: AttestationCycle = {
      id: "att-001",
      supplier_id: "sup-001-acme",
      cycle_year: 2026,
      status: "FOLLOW_UP_REQUIRED",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    const mockAssessment: Assessment = {
      id: "ass-001",
      attestation_id: "att-001",
      overall_risk_score: 52.5,
      risk_tier: "HIGH",
      environmental_score: 50.0,
      social_score: 85.0,
      governance_score: 60.0,
      summary_markdown: "Deficiencies noted",
      is_approved: false,
      findings: [
        {
          id: "find-001",
          pillar: "ENVIRONMENTAL",
          severity: "HIGH",
          standard_clause: "Clause E1.1: Scope 2 Reporting",
          shortfall_summary: "Missing Scope 2 emissions calculation",
          supplier_exact_quote: "We currently do not track Scope 2 emissions.",
          source_location: "Emissions Log",
          recommended_action: "Execute Scope 2 audit within 30 days.",
          review_decision: "PENDING",
        },
      ],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    const html = renderToString(
      <ComplianceAuditHub
        suppliers={mockSuppliers}
        cycles={[mockCycle]}
        assessmentsMap={{ "att-001": mockAssessment }}
        onOpenReport={() => {}}
        onOpenReviewGate={() => {}}
        onOpenDeficiencyLetter={() => {}}
      />
    );

    expect(html).toContain("Compliance Audit &amp; Legal Evidence Hub");
    expect(html).toContain("Total Identified Gaps");
    expect(html).toContain("Verbatim Supplier Evidence Quote");
    expect(html).toContain("We currently do not track Scope 2 emissions.");
  });

  it("StatCard renders title, value, subtitle, and trend badge", () => {
    const html = renderToString(
      <StatCard
        title="Active Attestations"
        value="85%"
        subtitle="17 of 20 Received"
        icon={ShieldCheck}
        trend="High Compliance"
        trendColor="emerald"
      />
    );

    expect(html).toContain("Active Attestations");
    expect(html).toContain("85%");
    expect(html).toContain("17 of 20 Received");
    expect(html).toContain("High Compliance");
  });

  it("BackendOfflineAlert displays error message", () => {
    const html = renderToString(
      <BackendOfflineAlert
        error="FastAPI Backend is not connected at http://localhost:8001"
        onRetry={() => {}}
      />
    );

    expect(html).toContain("Backend Connection Required");
    expect(html).toContain("FastAPI Backend is not connected");
    expect(html).toContain("Retry");
  });

  it("HeroBanner renders title and report trigger button", () => {
    const html = renderToString(<HeroBanner onOpenReport={() => {}} />);

    expect(html).toContain("Supplier Code-of-Conduct &amp; ESG Compliance");
    expect(html).toContain("Annual Attestation Cycle Active");
    expect(html).toContain("Executive Programme Report");
  });

  it("KpiStatsSection renders 4 KPI metric cards", () => {
    const mockReport: ProgrammeReport = {
      cycle_year: 2026,
      total_suppliers_invited: 10,
      responses_submitted: 8,
      attestation_rate_pct: 80.0,
      overall_programme_risk_level: "LOW",
      pillar_averages: {
        environmental_avg: 88.5,
        social_avg: 92.0,
        governance_avg: 85.0,
        overall_compliance_avg: 88.5,
      },
      risk_tier_breakdown: [
        { category: "LOW", count: 7, percentage: 70.0 },
        { category: "HIGH", count: 1, percentage: 10.0 },
      ],
      tier_distribution: [],
      regional_distribution: [],
      top_recurring_shortfalls: [],
      executive_narrative_markdown: "# Summary",
      generated_at: new Date().toISOString(),
    };

    const html = renderToString(<KpiStatsSection report={mockReport} />);

    expect(html).toContain("Suppliers Enrolled");
    expect(html).toContain("10");
    expect(html).toContain("Attestation Rate");
    expect(html).toContain("80%");
    expect(html).toContain("Avg Compliance Score");
    expect(html).toContain("88.5%");
  });

  it("SupplierDirectoryTable renders suppliers and status badges", () => {
    const html = renderToString(
      <SupplierDirectoryTable
        suppliers={mockSuppliers}
        cycles={[]}
        assessmentsMap={{}}
        selectedTier="ALL"
        onSelectTier={() => {}}
        onIssuePackage={() => {}}
        onUploadResponse={() => {}}
        onReviewGate={() => {}}
        onDeficiencyLetter={() => {}}
      />
    );

    expect(html).toContain("Acme Precision Components GmbH");
    expect(html).toContain("SUP-ACME-01");
    expect(html).toContain("NOT ISSUED");
    expect(html).toContain("Issue Package");
  });
});
