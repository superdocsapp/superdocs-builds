"use client";

import React, { useState } from "react";
import { Navbar, DashboardTab } from "./components/Navbar";
import { BackendOfflineAlert } from "./components/BackendOfflineAlert";
import { HeroBanner } from "./components/HeroBanner";
import { KpiStatsSection } from "./components/KpiStatsSection";
import {
  RiskDistributionDonut,
  TierRiskBarChart,
  PillarScoresCard,
} from "./components/Charts";
import { SupplierDirectoryTable } from "./components/SupplierDirectoryTable";
import { ComplianceAuditHub } from "./components/ComplianceAuditHub";
import { IssuanceModal } from "./components/IssuanceModal";
import { IngestionModal } from "./components/IngestionModal";
import { ReviewGateModal } from "./components/ReviewGateModal";
import { FollowUpLetterModal } from "./components/FollowUpLetterModal";
import { ProgrammeReportModal } from "./components/ProgrammeReportModal";
import { useAttestationCycle } from "./hooks/useAttestationCycle";
import { useProgrammeReport } from "./hooks/useProgrammeReport";
import { Supplier, AttestationCycle, Assessment } from "./types";

export default function Home() {
  const [activeTab, setActiveTab] = useState<DashboardTab>("operations");

  // Custom Hooks for Data Management
  const {
    suppliers,
    cycles,
    assessmentsMap,
    filteredSuppliers,
    loading: cycleLoading,
    error: cycleError,
    selectedTier,
    setSelectedTier,
    refresh: refreshCycleData,
  } = useAttestationCycle();

  const {
    report,
    loading: reportLoading,
    refresh: refreshReport,
  } = useProgrammeReport();

  // Modal States
  const [selectedSupplier, setSelectedSupplier] = useState<Supplier | null>(null);
  const [selectedCycle, setSelectedCycle] = useState<AttestationCycle | null>(null);
  const [selectedAssessment, setSelectedAssessment] = useState<Assessment | null>(null);

  const [isIssuanceOpen, setIsIssuanceOpen] = useState(false);
  const [isIngestionOpen, setIsIngestionOpen] = useState(false);
  const [isReviewOpen, setIsReviewOpen] = useState(false);
  const [isLetterOpen, setIsLetterOpen] = useState(false);
  const [isReportOpen, setIsReportOpen] = useState(false);

  const handleRefreshAll = () => {
    refreshCycleData();
    refreshReport();
  };

  return (
    <div className="min-h-screen pb-16">
      {/* Top Navbar with 3-Tab Switcher */}
      <Navbar
        onRefresh={handleRefreshAll}
        onOpenReport={() => setIsReportOpen(true)}
        loading={cycleLoading || reportLoading}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
      />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 space-y-8">
        {/* Backend Offline Alert */}
        {cycleError && <BackendOfflineAlert error={cycleError} onRetry={handleRefreshAll} />}

        {/* TAB 1: Supplier Operations */}
        {activeTab === "operations" && (
          <div className="space-y-8">
            <HeroBanner onOpenReport={() => setIsReportOpen(true)} />

            {/* Quick KPI stats row for quick context */}
            {report && <KpiStatsSection report={report} />}

            {/* Actionable Supplier Directory Table */}
            <SupplierDirectoryTable
              suppliers={suppliers}
              cycles={cycles}
              assessmentsMap={assessmentsMap}
              selectedTier={selectedTier}
              onSelectTier={setSelectedTier}
              onIssuePackage={(supplier) => {
                setSelectedSupplier(supplier);
                setIsIssuanceOpen(true);
              }}
              onUploadResponse={(supplier, cycle) => {
                setSelectedSupplier(supplier);
                setSelectedCycle(cycle);
                setIsIngestionOpen(true);
              }}
              onReviewGate={(supplier, assessment) => {
                setSelectedSupplier(supplier);
                setSelectedAssessment(assessment);
                setIsReviewOpen(true);
              }}
              onDeficiencyLetter={(supplier, cycle) => {
                setSelectedSupplier(supplier);
                setSelectedCycle(cycle);
                setIsLetterOpen(true);
              }}
            />
          </div>
        )}

        {/* TAB 2: Executive Analytics */}
        {activeTab === "analytics" && (
          <div className="space-y-8">
            <HeroBanner onOpenReport={() => setIsReportOpen(true)} />

            {/* KPI Stats Row */}
            {report && <KpiStatsSection report={report} />}

            {/* Charts Row */}
            {report && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <RiskDistributionDonut data={report.risk_tier_breakdown} />
                <TierRiskBarChart data={report.tier_distribution} />
                <PillarScoresCard scores={report.pillar_averages} />
              </div>
            )}
          </div>
        )}

        {/* TAB 3: Compliance & Audit Hub */}
        {activeTab === "audit" && (
          <ComplianceAuditHub
            suppliers={suppliers}
            cycles={cycles}
            assessmentsMap={assessmentsMap}
            onOpenReport={() => setIsReportOpen(true)}
            onOpenReviewGate={(supplier, assessment) => {
              setSelectedSupplier(supplier);
              setSelectedAssessment(assessment);
              setIsReviewOpen(true);
            }}
            onOpenDeficiencyLetter={(supplier, cycle) => {
              setSelectedSupplier(supplier);
              setSelectedCycle(cycle);
              setIsLetterOpen(true);
            }}
          />
        )}
      </main>

      {/* Modals */}
      <IssuanceModal
        supplier={selectedSupplier}
        isOpen={isIssuanceOpen}
        onClose={() => setIsIssuanceOpen(false)}
        onSuccess={handleRefreshAll}
      />

      <IngestionModal
        supplier={selectedSupplier}
        attestation={selectedCycle}
        isOpen={isIngestionOpen}
        onClose={() => setIsIngestionOpen(false)}
        onSuccess={handleRefreshAll}
      />

      <ReviewGateModal
        supplier={selectedSupplier}
        assessment={selectedAssessment}
        isOpen={isReviewOpen}
        onClose={() => setIsReviewOpen(false)}
        onSuccess={handleRefreshAll}
      />

      <FollowUpLetterModal
        supplier={selectedSupplier}
        attestation={selectedCycle}
        isOpen={isLetterOpen}
        onClose={() => setIsLetterOpen(false)}
      />

      <ProgrammeReportModal
        isOpen={isReportOpen}
        onClose={() => setIsReportOpen(false)}
      />
    </div>
  );
}
