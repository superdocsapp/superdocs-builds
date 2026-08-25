"use client";

import React, { useState, useEffect } from "react";
import { X, FileBarChart, Download, Sparkles, CheckCircle2 } from "lucide-react";
import { ProgrammeReport } from "../types";
import { api } from "../services/api";
import { config, buildApiUrl } from "../config";

interface ProgrammeReportModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ProgrammeReportModal: React.FC<ProgrammeReportModalProps> = ({
  isOpen,
  onClose,
}) => {
  const [report, setReport] = useState<ProgrammeReport | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      loadReport();
    }
  }, [isOpen]);

  const loadReport = async () => {
    setLoading(true);
    try {
      const data = await api.getProgrammeReport(2026);
      setReport(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
      <div className="glass-panel w-full max-w-4xl rounded-2xl overflow-hidden border border-white/10 shadow-2xl animate-in fade-in zoom-in duration-200 flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="p-6 border-b border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <FileBarChart className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-white text-lg">
                Annual Executive ESG Programme Report (2026)
              </h3>
              <p className="text-xs text-slate-400">
                Audited aggregate findings, response rates, and systemic risk profiles
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-white/5 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-6 overflow-y-auto flex-1 text-xs">
          {loading ? (
            <div className="p-12 text-center text-slate-400">Compiling aggregate audit report...</div>
          ) : report ? (
            <div className="space-y-6">
              {/* High Level KPI summary */}
              <div className="grid grid-cols-4 gap-4">
                <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                  <span className="text-slate-400">Total Suppliers:</span>
                  <p className="text-xl font-bold text-white mt-1">{report.total_suppliers_invited}</p>
                </div>
                <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                  <span className="text-slate-400">Attestation Rate:</span>
                  <p className="text-xl font-bold text-emerald-400 mt-1">{report.attestation_rate_pct}%</p>
                </div>
                <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                  <span className="text-slate-400">Average Compliance:</span>
                  <p className="text-xl font-bold text-blue-400 mt-1">{report.pillar_averages.overall_compliance_avg}%</p>
                </div>
                <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                  <span className="text-slate-400">Programme Risk Level:</span>
                  <p className="text-xl font-bold text-amber-400 mt-1">{report.overall_programme_risk_level}</p>
                </div>
              </div>

              {/* Top Recurring Shortfalls */}
              <div className="p-5 rounded-2xl bg-white/5 border border-white/10 space-y-3">
                <h4 className="font-semibold text-white uppercase tracking-wider text-[11px]">
                  Top Recurring Compliance Shortfalls Across Supply Base
                </h4>
                <div className="space-y-2">
                  {report.top_recurring_shortfalls.map((item, idx) => (
                    <div
                      key={idx}
                      className="p-3 rounded-lg bg-slate-900/80 border border-white/5 flex items-center justify-between"
                    >
                      <div className="flex items-center gap-2.5">
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/30">
                          {item.severity}
                        </span>
                        <span className="text-slate-200 font-medium">{item.standard_clause}</span>
                      </div>
                      <span className="text-slate-400 font-mono">
                        {item.occurrence_count} flagged supplier(s)
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Narrative Report */}
              <div className="p-6 rounded-2xl bg-slate-950/80 border border-white/10 font-mono text-slate-200 whitespace-pre-wrap leading-relaxed">
                {report.executive_narrative_markdown}
              </div>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-white/10 flex justify-between items-center bg-white/[0.02]">
          <span className="text-xs text-slate-400">
            Reconciles mathematically with individual supplier assessments.
          </span>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs text-slate-300 hover:text-white hover:bg-white/5 transition-colors"
            >
              Close
            </button>
            <a
              href={buildApiUrl(config.api.endpoints.downloadDocument("executive_programme_report_2026", "pdf"))}
              target="_blank"
              rel="noreferrer"
              className="px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 font-semibold text-xs transition-all shadow-lg shadow-emerald-500/20 flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Download Report (PDF)
            </a>
          </div>
        </div>
      </div>
    </div>
  );
};
