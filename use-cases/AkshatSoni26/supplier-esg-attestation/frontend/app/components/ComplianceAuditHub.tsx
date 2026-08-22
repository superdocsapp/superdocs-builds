"use client";

import React, { useState } from "react";
import {
  FileText,
  FileCheck2,
  AlertTriangle,
  Mail,
  Download,
  CheckCircle2,
  Clock,
  Sparkles,
  ExternalLink,
  ShieldAlert,
} from "lucide-react";
import { Supplier, AttestationCycle, Assessment, FollowUpLetter } from "../types";
import { config, buildApiUrl } from "../config";

interface ComplianceAuditHubProps {
  suppliers: Supplier[];
  cycles: AttestationCycle[];
  assessmentsMap: Record<string, Assessment>;
  onOpenReport: () => void;
  onOpenReviewGate: (supplier: Supplier, assessment: Assessment) => void;
  onOpenDeficiencyLetter: (supplier: Supplier, cycle: AttestationCycle) => void;
}

export function ComplianceAuditHub({
  suppliers,
  cycles,
  assessmentsMap,
  onOpenReport,
  onOpenReviewGate,
  onOpenDeficiencyLetter,
}: ComplianceAuditHubProps) {
  // Aggregate all findings across suppliers
  const allAuditedFindings: Array<{
    findingId: string;
    supplier: Supplier;
    cycle: AttestationCycle;
    assessment: Assessment;
    finding: any;
  }> = [];

  suppliers.forEach((supplier) => {
    const cycle = cycles.find((c) => c.supplier_id === supplier.id);
    if (cycle && assessmentsMap[cycle.id]) {
      const assessment = assessmentsMap[cycle.id];
      (assessment.findings || []).forEach((finding) => {
        allAuditedFindings.push({
          findingId: finding.id,
          supplier,
          cycle,
          assessment,
          finding,
        });
      });
    }
  });

  const totalFindingsCount = allAuditedFindings.length;
  const criticalFindingsCount = allAuditedFindings.filter(
    (f) => f.finding.severity === "CRITICAL"
  ).length;
  const highFindingsCount = allAuditedFindings.filter(
    (f) => f.finding.severity === "HIGH"
  ).length;

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="glass-panel p-6 sm:p-8 rounded-3xl relative overflow-hidden flex flex-col md:flex-row items-start md:items-center justify-between gap-6 border border-white/10 shadow-2xl">
        <div className="space-y-2 max-w-2xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-500/15 border border-purple-500/30 text-purple-300 text-xs font-mono font-medium">
            <Sparkles className="w-3.5 h-3.5 text-purple-400" />
            Audit Trail & Evidence Repository · {config.app.defaultCycleYear}
          </div>
          <h2 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
            Compliance Audit & Legal Evidence Hub
          </h2>
          <p className="text-xs sm:text-sm text-slate-300 leading-relaxed font-normal">
            Inspect verbatim supplier quotes, track human review gate approvals, and audit auto-drafted deficiency notices.
          </p>
        </div>

        <button
          onClick={onOpenReport}
          className="px-5 py-3.5 rounded-2xl bg-gradient-to-r from-purple-500 to-indigo-500 hover:from-purple-600 hover:to-indigo-600 text-white font-semibold text-xs sm:text-sm transition-all shadow-xl shadow-purple-500/25 flex items-center gap-2.5 shrink-0 cursor-pointer active:scale-98"
        >
          <Download className="w-4 h-4" />
          Download Executive Audit PDF
        </button>
      </div>

      {/* Audit Highlights */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        <div className="glass-panel p-5 rounded-2xl border border-white/10 shadow-xl flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Identified Gaps</p>
            <h3 className="text-2xl font-bold text-white mt-1">{totalFindingsCount}</h3>
            <p className="text-xs text-slate-400 mt-0.5">Across all enrolled suppliers</p>
          </div>
          <div className="p-3 rounded-xl bg-purple-500/15 border border-purple-500/30 text-purple-400">
            <FileCheck2 className="w-5 h-5" />
          </div>
        </div>

        <div className="glass-panel p-5 rounded-2xl border border-white/10 shadow-xl flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Critical Labor Violations</p>
            <h3 className="text-2xl font-bold text-rose-400 mt-1">{criticalFindingsCount}</h3>
            <p className="text-xs text-slate-400 mt-0.5">ILO & statutory overtime caps</p>
          </div>
          <div className="p-3 rounded-xl bg-rose-500/15 border border-rose-500/30 text-rose-400">
            <ShieldAlert className="w-5 h-5" />
          </div>
        </div>

        <div className="glass-panel p-5 rounded-2xl border border-white/10 shadow-xl flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">High Governance Risks</p>
            <h3 className="text-2xl font-bold text-amber-400 mt-1">{highFindingsCount}</h3>
            <p className="text-xs text-slate-400 mt-0.5">Missing Scope 2 / Anti-Bribery</p>
          </div>
          <div className="p-3 rounded-xl bg-amber-500/15 border border-amber-500/30 text-amber-400">
            <AlertTriangle className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* Verbatim Evidence & Findings Audit Table */}
      <div className="glass-panel rounded-3xl overflow-hidden border border-white/10 p-6 space-y-4 shadow-2xl">
        <div>
          <h3 className="font-bold text-white text-lg tracking-tight">
            Verbatim Evidence & Non-Compliance Findings Audit
          </h3>
          <p className="text-xs text-slate-300 font-normal">
            Directly extracts and cites exact sentences from uploaded supplier documents for defensible legal proof.
          </p>
        </div>

        {allAuditedFindings.length === 0 ? (
          <div className="p-12 text-center text-slate-400 text-xs">
            No compliance gaps identified. All normalized suppliers are currently 100% compliant.
          </div>
        ) : (
          <div className="space-y-3">
            {allAuditedFindings.map(({ findingId, supplier, cycle, assessment, finding }) => (
              <div
                key={findingId}
                className="p-4 rounded-2xl bg-white/[0.02] border border-white/10 hover:border-white/20 transition-colors space-y-2.5"
              >
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={`px-2 py-0.5 rounded font-mono text-[10px] font-bold uppercase border ${
                        finding.severity === "CRITICAL"
                          ? "bg-rose-500/15 text-rose-300 border-rose-500/30"
                          : finding.severity === "HIGH"
                          ? "bg-amber-500/15 text-amber-300 border-amber-500/30"
                          : "bg-blue-500/15 text-blue-300 border-blue-500/30"
                      }`}
                    >
                      {finding.severity}
                    </span>
                    <span className="font-bold text-white text-xs">{supplier.name}</span>
                    <span className="text-slate-400 font-mono text-[11px]">({supplier.code})</span>
                    <span className="text-slate-400 text-xs">·</span>
                    <span className="text-purple-300 font-medium text-xs">{finding.standard_clause}</span>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => onOpenReviewGate(supplier, assessment)}
                      className="px-3 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/30 font-semibold text-[11px] transition-colors cursor-pointer"
                    >
                      Review Gate
                    </button>
                    <button
                      onClick={() => onOpenDeficiencyLetter(supplier, cycle)}
                      className="px-3 py-1 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 border border-purple-500/30 font-semibold text-[11px] transition-colors cursor-pointer"
                    >
                      Deficiency Notice
                    </button>
                  </div>
                </div>

                <div className="text-xs text-slate-300">
                  <strong className="text-white">Shortfall:</strong> {finding.shortfall_summary}
                </div>

                {/* Verbatim Supplier Quote */}
                <div className="p-3 rounded-xl bg-slate-950/80 border border-white/10 text-xs font-mono text-slate-200">
                  <div className="text-[10px] text-slate-400 uppercase font-semibold mb-1 flex items-center gap-1.5">
                    <span>Verbatim Supplier Evidence Quote</span>
                    <span className="text-slate-500">({finding.source_location || "Response Log"})</span>
                  </div>
                  <blockquote className="italic text-rose-300/90 pl-2 border-l-2 border-rose-500/50">
                    &ldquo;{finding.supplier_exact_quote}&rdquo;
                  </blockquote>
                </div>

                <div className="text-xs text-slate-400 flex items-center justify-between">
                  <div>
                    <strong className="text-slate-300">Mandated Action:</strong> {finding.recommended_action}
                  </div>
                  <span className="font-mono text-[10px] uppercase font-bold text-slate-400">
                    Review Decision: {finding.review_decision || "PENDING"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
