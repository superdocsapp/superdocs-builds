"use client";

import React, { useState, useEffect } from "react";
import { X, Mail, Download, CheckCircle, Send, FileText, AlertTriangle, Sparkles } from "lucide-react";
import { Supplier, AttestationCycle, FollowUpLetter } from "../types";
import { api } from "../services/api";
import { config } from "../config";

interface FollowUpLetterModalProps {
  supplier: Supplier | null;
  attestation: AttestationCycle | null;
  isOpen: boolean;
  onClose: () => void;
}

export const FollowUpLetterModal: React.FC<FollowUpLetterModalProps> = ({
  supplier,
  attestation,
  isOpen,
  onClose,
}) => {
  const [letters, setLetters] = useState<FollowUpLetter[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && attestation) {
      loadLetters();
    }
  }, [isOpen, attestation]);

  const loadLetters = async () => {
    if (!attestation) return;
    setLoading(true);
    try {
      const data = await api.getLettersByAttestation(attestation.id);
      setLetters(data);
    } catch {
      // no existing letters yet
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    if (!attestation) return;
    setGenerating(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const newLetter = await api.generateFollowUpLetter(attestation.id, 30);
      setLetters((prev) => [newLetter, ...prev]);
      setSuccessMsg("Deficiency follow-up letter generated with verbatim quotes and registered in SuperDocs!");
    } catch (err: any) {
      setError(err.message || "Failed to generate follow-up letter");
    } finally {
      setGenerating(false);
    }
  };

  const handleUpdateStatus = async (letterId: string, status: "DRAFT" | "APPROVED" | "SENT") => {
    try {
      const updated = await api.updateLetterStatus(letterId, status);
      setLetters((prev) => prev.map((l) => (l.id === letterId ? updated : l)));
    } catch (err: any) {
      setError(err.message || "Failed to update status");
    }
  };

  if (!isOpen || !supplier || !attestation) return null;

  const currentLetter = letters[0];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
      <div className="glass-panel w-full max-w-4xl rounded-2xl overflow-hidden border border-white/10 shadow-2xl animate-in fade-in zoom-in duration-200 flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="p-6 border-b border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400">
              <Mail className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-white text-lg">Supplier Deficiency Follow-Up Notice</h3>
              <p className="text-xs text-slate-400">
                Targeted remediation notice quoting {supplier.name}'s actual responses back to them
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
        <div className="p-6 space-y-5 overflow-y-auto flex-1">
          {error && (
            <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs">
              {error}
            </div>
          )}

          {successMsg && (
            <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs flex items-center gap-2">
              <CheckCircle className="w-4 h-4 text-emerald-400" />
              <span>{successMsg}</span>
            </div>
          )}

          {!currentLetter ? (
            <div className="p-12 text-center rounded-2xl bg-white/[0.02] border border-white/10 space-y-4">
              <div className="w-12 h-12 rounded-2xl bg-purple-500/10 text-purple-400 flex items-center justify-center mx-auto">
                <FileText className="w-6 h-6" />
              </div>
              <div className="max-w-md mx-auto">
                <h4 className="font-semibold text-white text-base">No Follow-Up Letter Drafted Yet</h4>
                <p className="text-xs text-slate-400 mt-1">
                  Draft a formal corrective action letter that automatically extracts all accepted shortfall findings and quotes the supplier's exact words.
                </p>
              </div>
              <button
                onClick={handleGenerate}
                disabled={generating}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-purple-500 to-indigo-500 hover:from-purple-400 hover:to-indigo-400 text-white font-semibold text-xs transition-all shadow-lg shadow-purple-500/20 inline-flex items-center gap-2 disabled:opacity-50"
              >
                {generating ? "Drafting Letter via SuperDocs..." : "Draft Evidence-Quoted Letter"}
              </button>
            </div>
          ) : (
            <div className="space-y-4 animate-in fade-in">
              {/* Metadata Bar */}
              <div className="p-4 rounded-xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-3 text-xs">
                <div className="space-y-0.5">
                  <span className="text-slate-400">Subject:</span>
                  <p className="font-medium text-white">{currentLetter.subject}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-slate-400">Status:</span>
                  <span className={`px-2.5 py-1 rounded-full font-mono text-[10px] uppercase font-semibold ${
                    currentLetter.status === "SENT" ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30" :
                    currentLetter.status === "APPROVED" ? "bg-blue-500/20 text-blue-400 border border-blue-500/30" :
                    "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                  }`}>
                    {currentLetter.status}
                  </span>
                </div>
              </div>

              {/* Letter Preview */}
              <div className="p-6 rounded-2xl bg-slate-950/90 border border-white/10 text-xs text-slate-200 font-mono whitespace-pre-wrap leading-relaxed max-h-80 overflow-y-auto">
                {currentLetter.content_markdown}
              </div>

              {/* Actions & Export */}
              <div className="flex justify-between items-center text-xs pt-2">
                <div className="flex gap-2">
                  {currentLetter.status === "DRAFT" && (
                    <button
                      onClick={() => handleUpdateStatus(currentLetter.id, "APPROVED")}
                      className="px-3 py-1.5 rounded-lg bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 border border-blue-500/20 transition-colors"
                    >
                      Approve for Dispatch
                    </button>
                  )}
                  {currentLetter.status === "APPROVED" && (
                    <button
                      onClick={() => handleUpdateStatus(currentLetter.id, "SENT")}
                      className="px-3 py-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/20 transition-colors flex items-center gap-1.5"
                    >
                      <Send className="w-3.5 h-3.5" />
                      Mark as Dispatched
                    </button>
                  )}
                </div>

                {currentLetter.superdocs_export_url && (
                  <a
                    href={
                      currentLetter.superdocs_export_url.startsWith("http")
                        ? currentLetter.superdocs_export_url
                        : `${config.api.baseUrl.replace(/\/api\/v1\/?$/, "")}${currentLetter.superdocs_export_url}`
                    }
                    target="_blank"
                    rel="noreferrer"
                    className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-white font-medium flex items-center gap-2 transition-colors"
                  >
                    <Download className="w-3.5 h-3.5 text-emerald-400" />
                    Export PDF / Word
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
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
