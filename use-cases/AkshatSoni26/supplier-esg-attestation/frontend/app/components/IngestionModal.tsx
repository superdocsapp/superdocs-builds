"use client";

import React, { useState } from "react";
import { X, Upload, FileText, CheckCircle2, AlertCircle, Sparkles } from "lucide-react";
import { Supplier, AttestationCycle } from "../types";
import { api } from "../services/api";

interface IngestionModalProps {
  supplier: Supplier | null;
  attestation: AttestationCycle | null;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export const IngestionModal: React.FC<IngestionModalProps> = ({
  supplier,
  attestation,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen || !supplier || !attestation) return null;

  const handleUpload = async () => {
    if (!file) {
      setError("Please select a file to upload.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.uploadResponse(attestation.id, file, true);
      setResult(res);
      onSuccess();
    } catch (err: any) {
      setError(err.message || "Upload and normalization failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="glass-panel w-full max-w-xl rounded-2xl overflow-hidden border border-white/10 shadow-2xl animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="p-6 border-b border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400">
              <Upload className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-white text-lg">Ingest Supplier Response</h3>
              <p className="text-xs text-slate-400">
                Multi-format ingestion & SuperDocs ESG normalization
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
        <div className="p-6 space-y-5">
          {error && (
            <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs">
              {error}
            </div>
          )}

          {/* Supplier Info */}
          <div className="p-4 rounded-xl bg-white/5 border border-white/10 flex justify-between items-center text-xs">
            <div>
              <h4 className="font-semibold text-white">{supplier.name}</h4>
              <p className="text-slate-400 font-mono mt-0.5">{supplier.code} · {supplier.tier}</p>
            </div>
            <span className="px-2.5 py-1 rounded-full bg-blue-500/10 text-blue-400 font-mono border border-blue-500/20">
              Attestation #{attestation.cycle_year}
            </span>
          </div>

          {!result ? (
            <div className="space-y-4">
              {/* File Dropzone */}
              <label
                htmlFor="response-file-input"
                className="border-2 border-dashed border-white/20 hover:border-emerald-500/50 rounded-2xl p-8 flex flex-col items-center justify-center cursor-pointer transition-all bg-white/[0.02] hover:bg-white/[0.04] group"
              >
                <div className="p-4 rounded-2xl bg-white/5 group-hover:bg-emerald-500/10 text-slate-300 group-hover:text-emerald-400 transition-colors mb-3">
                  <FileText className="w-8 h-8" />
                </div>
                <p className="text-sm font-medium text-white">
                  {file ? file.name : "Click or drag supplier response file here"}
                </p>
                <p className="text-xs text-slate-400 mt-1">
                  Supported formats: <strong>.PDF, .DOCX, .TXT, .MD, .JSON</strong>
                </p>
                <input
                  id="response-file-input"
                  type="file"
                  accept=".pdf,.docx,.doc,.txt,.md,.json"
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files && e.target.files[0]) {
                      setFile(e.target.files[0]);
                    }
                  }}
                />
              </label>

              <div className="p-3.5 rounded-xl bg-slate-900/60 border border-white/5 text-xs text-slate-300 flex items-start gap-2.5">
                <Sparkles className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <p>
                  <strong>Automatic Normalization:</strong> The engine extracts environmental, social, and governance disclosures, calculates ESG scores, and pinpoints exact verbatim quotes for compliance discrepancies.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-4 animate-in fade-in">
              <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                <span>
                  <strong>Success!</strong> File {result.filename} ingested ({result.characters_extracted} characters extracted).
                </span>
              </div>

              <div className="p-4 rounded-xl bg-slate-900/80 border border-white/10 space-y-2 text-xs text-slate-300">
                <div className="flex justify-between">
                  <span>SuperDocs Doc ID:</span>
                  <code className="text-emerald-400">{result.superdocs_document_id}</code>
                </div>
                <div className="flex justify-between">
                  <span>Assessment Generated:</span>
                  <code className="text-blue-400">{result.assessment_id}</code>
                </div>
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
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button
              onClick={handleUpload}
              disabled={loading || !file}
              className="px-5 py-2 rounded-xl bg-gradient-to-r from-blue-500 to-indigo-500 hover:from-blue-400 hover:to-indigo-400 text-white font-semibold text-xs transition-all shadow-lg shadow-blue-500/20 flex items-center gap-2 disabled:opacity-50"
            >
              {loading ? (
                <>Normalizing Response...</>
              ) : (
                <>
                  <Upload className="w-3.5 h-3.5" />
                  Ingest & Normalize
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
