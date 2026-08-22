"use client";

import React, { useState } from "react";
import { X, Check, CheckCircle, ShieldAlert, AlertTriangle, MessageSquare, Quote, FileCheck } from "lucide-react";
import { Supplier, Assessment, ReviewDecision, Finding } from "../types";
import { api } from "../services/api";

interface ReviewGateModalProps {
  supplier: Supplier | null;
  assessment: Assessment | null;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export const ReviewGateModal: React.FC<ReviewGateModalProps> = ({
  supplier,
  assessment,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [decisions, setDecisions] = useState<Record<string, ReviewDecision>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [reviewerName, setReviewerName] = useState("Responsible Sourcing Lead");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen || !supplier || !assessment) return null;

  const findings = assessment.findings || [];

  const handleDecisionChange = (findingId: string, decision: ReviewDecision) => {
    setDecisions((prev) => ({ ...prev, [findingId]: decision }));
  };

  const handleNotesChange = (findingId: string, text: string) => {
    setNotes((prev) => ({ ...prev, [findingId]: text }));
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    try {
      const findingDecisions = findings.map((f) => ({
        finding_id: f.id,
        review_decision: decisions[f.id] || f.review_decision || "PENDING",
        review_notes: notes[f.id] || f.review_notes || "",
      }));

      await api.submitReview(assessment.id, true, reviewerName, findingDecisions);
      onSuccess();
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to commit review decisions");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
      <div className="glass-panel w-full max-w-4xl rounded-2xl overflow-hidden border border-white/10 shadow-2xl animate-in fade-in zoom-in duration-200 flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="p-6 border-b border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-white text-lg">Human-in-the-Loop Review Gate</h3>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  Gate Control Active
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Item-by-item verification for {supplier.name} ({supplier.code})
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

        {/* Scrollable Body */}
        <div className="p-6 space-y-6 overflow-y-auto flex-1">
          {error && (
            <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs">
              {error}
            </div>
          )}

          {/* Assessment Summary Header */}
          <div className="grid grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-white/5 border border-white/10">
              <p className="text-[10px] text-slate-400 uppercase font-medium">Overall Risk</p>
              <h4 className="text-xl font-bold text-white mt-1">{assessment.overall_risk_score}/100</h4>
              <span className={`inline-block mt-1 text-[10px] font-mono px-2 py-0.5 rounded ${
                assessment.risk_tier === "CRITICAL" ? "bg-rose-500/20 text-rose-400 border border-rose-500/30" :
                assessment.risk_tier === "HIGH" ? "bg-orange-500/20 text-orange-400 border border-orange-500/30" :
                assessment.risk_tier === "MEDIUM" ? "bg-amber-500/20 text-amber-400 border border-amber-500/30" :
                "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
              }`}>
                {assessment.risk_tier} RISK
              </span>
            </div>

            <div className="p-4 rounded-xl bg-white/5 border border-white/10">
              <p className="text-[10px] text-slate-400 uppercase font-medium">Environmental</p>
              <h4 className="text-xl font-bold text-emerald-400 mt-1">{assessment.environmental_score}%</h4>
              <p className="text-[10px] text-slate-500 mt-1">GHG & ISO 14001</p>
            </div>

            <div className="p-4 rounded-xl bg-white/5 border border-white/10">
              <p className="text-[10px] text-slate-400 uppercase font-medium">Social & Labor</p>
              <h4 className="text-xl font-bold text-blue-400 mt-1">{assessment.social_score}%</h4>
              <p className="text-[10px] text-slate-500 mt-1">Hours & Living Wage</p>
            </div>

            <div className="p-4 rounded-xl bg-white/5 border border-white/10">
              <p className="text-[10px] text-slate-400 uppercase font-medium">Governance</p>
              <h4 className="text-xl font-bold text-purple-400 mt-1">{assessment.governance_score}%</h4>
              <p className="text-[10px] text-slate-500 mt-1">Anti-Bribery & Audit</p>
            </div>
          </div>

          {/* Finding Cards with Exact Verbatim Quotes */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-slate-200 uppercase tracking-wider">
                Identified Compliance Findings ({findings.length})
              </h4>
              <span className="text-xs text-slate-400">
                Rejecting one finding does not discard the rest
              </span>
            </div>

            {findings.length === 0 ? (
              <div className="p-8 text-center rounded-2xl bg-emerald-500/5 border border-emerald-500/20 text-emerald-400 space-y-2">
                <CheckCircle className="w-8 h-8 mx-auto" />
                <h5 className="font-semibold text-sm">Honest Zero-Finding Report</h5>
                <p className="text-xs text-slate-400">
                  This supplier meets or exceeds all statutory and ESG standards. No remediation required.
                </p>
              </div>
            ) : (
              findings.map((f, idx) => {
                const currentDecision = decisions[f.id] || f.review_decision || "PENDING";

                return (
                  <div
                    key={f.id}
                    className={`p-5 rounded-2xl border transition-all ${
                      currentDecision === "ACCEPTED"
                        ? "bg-amber-500/[0.04] border-amber-500/30"
                        : currentDecision === "REJECTED"
                        ? "bg-slate-900/40 border-white/5 opacity-60"
                        : "bg-slate-900/80 border-white/10"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="space-y-2 flex-1">
                        <div className="flex items-center gap-2">
                          <span className={`text-[10px] font-mono px-2 py-0.5 rounded font-semibold ${
                            f.severity === "CRITICAL" ? "bg-rose-500/20 text-rose-400 border border-rose-500/30" :
                            f.severity === "HIGH" ? "bg-orange-500/20 text-orange-400 border border-orange-500/30" :
                            "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                          }`}>
                            {f.severity}
                          </span>
                          <span className="text-xs font-mono text-slate-400">#{idx + 1}</span>
                          <h5 className="text-sm font-semibold text-white">{f.standard_clause}</h5>
                        </div>

                        <p className="text-xs text-slate-300">{f.shortfall_summary}</p>

                        {/* Exact Verbatim Quote Block */}
                        <div className="p-3.5 rounded-xl bg-slate-950/80 border border-white/10 text-xs space-y-1.5">
                          <div className="flex items-center gap-1.5 text-emerald-400 text-[11px] font-medium">
                            <Quote className="w-3.5 h-3.5" />
                            <span>Supplier Submitted Response (Verbatim Citation):</span>
                          </div>
                          <blockquote className="italic text-slate-200 pl-3 border-l-2 border-emerald-500/50">
                            "{f.supplier_exact_quote}"
                          </blockquote>
                          {f.source_location && (
                            <p className="text-[10px] font-mono text-slate-500">Source: {f.source_location}</p>
                          )}
                        </div>

                        {/* Recommended Action */}
                        <div className="text-xs text-slate-400 pt-1">
                          <strong className="text-slate-300">Mandated Action:</strong> {f.recommended_action}
                        </div>
                      </div>

                      {/* Item-by-Item Decision Toggles */}
                      <div className="flex flex-col gap-2 shrink-0">
                        <button
                          onClick={() => handleDecisionChange(f.id, "ACCEPTED")}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 ${
                            currentDecision === "ACCEPTED"
                              ? "bg-amber-500 text-slate-950 font-semibold shadow-md shadow-amber-500/20"
                              : "bg-white/5 hover:bg-white/10 text-slate-300 border border-white/10"
                          }`}
                        >
                          <Check className="w-3.5 h-3.5" />
                          Accept Finding
                        </button>

                        <button
                          onClick={() => handleDecisionChange(f.id, "REJECTED")}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 ${
                            currentDecision === "REJECTED"
                              ? "bg-rose-500 text-white font-semibold"
                              : "bg-white/5 hover:bg-white/10 text-slate-300 border border-white/10"
                          }`}
                        >
                          <X className="w-3.5 h-3.5" />
                          Dismiss Finding
                        </button>
                      </div>
                    </div>

                    {/* Review Notes */}
                    <div className="mt-3 pt-3 border-t border-white/5">
                      <input
                        type="text"
                        placeholder="Add auditor review notes or dispensation rationale..."
                        defaultValue={f.review_notes || ""}
                        onChange={(e) => handleNotesChange(f.id, e.target.value)}
                        className="w-full px-3 py-1.5 rounded-lg bg-black/40 border border-white/10 text-xs text-white placeholder:text-slate-500 focus:outline-none focus:border-emerald-500/50"
                      />
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Reviewer Details */}
          <div className="p-4 rounded-xl bg-white/5 border border-white/10 flex items-center justify-between gap-4">
            <div className="text-xs text-slate-300">
              <span>Auditor / Reviewer:</span>
            </div>
            <input
              type="text"
              value={reviewerName}
              onChange={(e) => setReviewerName(e.target.value)}
              className="px-3 py-1.5 rounded-lg bg-slate-900 border border-white/10 text-xs text-white focus:outline-none focus:border-emerald-500/50 w-64"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-white/10 flex justify-between items-center bg-white/[0.02]">
          <span className="text-xs text-slate-400">
            Commits accepted findings into the final approved assessment document.
          </span>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs text-slate-300 hover:text-white hover:bg-white/5 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={loading}
              className="px-5 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-emerald-500 hover:from-amber-400 hover:to-emerald-400 text-slate-950 font-semibold text-xs transition-all shadow-lg shadow-emerald-500/20 flex items-center gap-2 disabled:opacity-50"
            >
              {loading ? (
                <>Committing Review Decisions...</>
              ) : (
                <>
                  <FileCheck className="w-4 h-4" />
                  Commit Decisions & Complete Gate
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
