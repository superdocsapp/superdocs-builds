"use client";

import React, { useState } from "react";
import { X, Send, FileCheck, Layers, Globe, Sparkles } from "lucide-react";
import { Supplier } from "../types";
import { api } from "../services/api";
import { config } from "../config";

interface IssuanceModalProps {
  supplier: Supplier | null;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export const IssuanceModal: React.FC<IssuanceModalProps> = ({
  supplier,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [loading, setLoading] = useState(false);
  const [issuedDoc, setIssuedDoc] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen || !supplier) return null;

  const handleIssue = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.issueQuestionnaire(supplier.id, 2026);
      setIssuedDoc(res);
      onSuccess();
    } catch (err: any) {
      setError(err.message || "Issuance failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="glass-panel w-full max-w-2xl rounded-2xl overflow-hidden border border-white/10 shadow-2xl animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="p-6 border-b border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <FileCheck className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-white text-lg">Issue ESG Attestation Package</h3>
              <p className="text-xs text-slate-400">
                Generating localized Code-of-Conduct & Tier-specific Questionnaires
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
        <div className="p-6 space-y-5 max-h-[70vh] overflow-y-auto">
          {error && (
            <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs">
              {error}
            </div>
          )}

          {/* Supplier Metadata Card */}
          <div className="p-4 rounded-xl bg-white/5 border border-white/10 space-y-3">
            <div className="flex justify-between items-start">
              <div>
                <h4 className="font-semibold text-white text-sm">{supplier.name}</h4>
                <p className="text-xs text-slate-400 font-mono mt-0.5">{supplier.code}</p>
              </div>
              <span className="px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 font-mono text-xs border border-emerald-500/20">
                {supplier.tier}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3 pt-2 text-xs text-slate-300">
              <div className="flex items-center gap-2">
                <Globe className="w-4 h-4 text-slate-400" />
                <span>Region: <strong>{supplier.region} ({supplier.country})</strong></span>
              </div>
              <div className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-slate-400" />
                <span>Contact: <strong>{supplier.primary_contact_email}</strong></span>
              </div>
            </div>
          </div>

          {/* Package Configuration */}
          {!issuedDoc ? (
            <div className="space-y-3">
              <h5 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                Included Documentation Modules:
              </h5>
              <div className="space-y-2 text-xs">
                <div className="p-3 rounded-lg bg-slate-900/60 border border-white/5 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-emerald-400" />
                    <span>Global Supplier Code of Conduct (Master Charter 2026.1)</span>
                  </div>
                  <span className="text-[10px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded">
                    Mandatory
                  </span>
                </div>

                <div className="p-3 rounded-lg bg-slate-900/60 border border-white/5 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Layers className="w-4 h-4 text-blue-400" />
                    <span>
                      {supplier.tier === "TIER_1_STRATEGIC"
                        ? "Annex T1: Scope 1-3 Deep GHG & ISO 14001 Audit Questionnaire"
                        : supplier.tier === "TIER_2_MANUFACTURING"
                        ? "Annex T2: Manufacturing Workplace & Fair Labor Standards Questionnaire"
                        : "Annex T3: Commodity & Indirect Statutory Compliance Questionnaire"}
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded">
                    Tier-Specific
                  </span>
                </div>

                <div className="p-3 rounded-lg bg-slate-900/60 border border-white/5 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Globe className="w-4 h-4 text-purple-400" />
                    <span>
                      {supplier.region === "EU"
                        ? "Annex R-EU: EU CSRD, CSDDD & REACH Statutory Addendum"
                        : supplier.region === "NORTH_AMERICA"
                        ? "Annex R-US: US UFLPA Forced Labor & Conflict Minerals Addendum"
                        : "Annex R-APAC: APAC Ethical Recruitment & Discharge Addendum"}
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded">
                    Regional Law
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-4 animate-in fade-in">
              <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs flex items-center gap-2">
                <FileCheck className="w-4 h-4 text-emerald-400" />
                <span>Package successfully compiled and registered on SuperDocs!</span>
              </div>

              <div className="p-4 rounded-xl bg-slate-950/80 border border-white/10 font-mono text-xs text-slate-300 max-h-48 overflow-y-auto whitespace-pre-wrap">
                {issuedDoc.document_content_markdown}
              </div>

              <div className="flex justify-between items-center text-xs text-slate-400">
                <span>SuperDocs Doc ID: <code className="text-emerald-400">{issuedDoc.superdocs_document_id}</code></span>
                {issuedDoc.export_url && (
                  <a
                    href={
                      issuedDoc.export_url.startsWith("http")
                        ? issuedDoc.export_url
                        : `${config.api.baseUrl.replace(/\/api\/v1\/?$/, "")}${issuedDoc.export_url}`
                    }
                    target="_blank"
                    rel="noreferrer"
                    className="text-emerald-400 underline hover:text-emerald-300 font-medium flex items-center gap-1"
                  >
                    Download Export (PDF)
                  </a>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-white/10 flex justify-end gap-3 bg-white/[0.02]">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs text-slate-300 hover:text-white hover:bg-white/5 transition-colors"
          >
            {issuedDoc ? "Close" : "Cancel"}
          </button>
          {!issuedDoc && (
            <button
              onClick={handleIssue}
              disabled={loading}
              className="px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 font-semibold text-xs transition-all shadow-lg shadow-emerald-500/20 flex items-center gap-2 disabled:opacity-50"
            >
              {loading ? (
                <>Compiling with SuperDocs...</>
              ) : (
                <>
                  <Send className="w-3.5 h-3.5" />
                  Issue Package to Supplier
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
