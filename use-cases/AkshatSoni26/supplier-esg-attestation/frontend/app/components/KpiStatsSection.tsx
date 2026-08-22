import React from "react";
import { Building2, FileCheck2, AlertTriangle, ShieldCheck } from "lucide-react";
import { StatCard } from "./StatCard";
import { ProgrammeReport } from "../types";

interface KpiStatsSectionProps {
  report: ProgrammeReport;
}

export function KpiStatsSection({ report }: KpiStatsSectionProps) {
  const highCriticalRiskCount =
    (report.risk_tier_breakdown.find((r) => r.category === "CRITICAL")?.count || 0) +
    (report.risk_tier_breakdown.find((r) => r.category === "HIGH")?.count || 0);

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
      <StatCard
        title="Suppliers Enrolled"
        value={report.total_suppliers_invited}
        subtitle="Tiers 1, 2 & 3"
        icon={Building2}
        trend="100% In-Scope"
        trendColor="indigo"
      />
      <StatCard
        title="Attestation Rate"
        value={`${report.attestation_rate_pct}%`}
        subtitle={`${report.responses_submitted}/${report.total_suppliers_invited} Responses Returned`}
        icon={FileCheck2}
        trend="Annual Cycle Progress"
        trendColor="emerald"
      />
      <StatCard
        title="High / Critical Risks"
        value={highCriticalRiskCount}
        subtitle="Requires Follow-Up Remediation"
        icon={AlertTriangle}
        trend="Flagged Gaps"
        trendColor="rose"
      />
      <StatCard
        title="Avg Compliance Score"
        value={`${report.pillar_averages.overall_compliance_avg}%`}
        subtitle="E, S & G Composite"
        icon={ShieldCheck}
        trend="Audited Benchmarks"
        trendColor="amber"
      />
    </div>
  );
}
