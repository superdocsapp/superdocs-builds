import React, { useState } from 'react';
import {
  ShieldCheck,
  Clock,
  CheckCircle2,
  Send,
  Loader2,
  Copy,
  Check,
  FileText,
  RefreshCw
} from 'lucide-react';
import { ClientBatchRecord } from '../types';

interface MissingItemsFollowUpProps {
  records: ClientBatchRecord[];
  onDraftFollowUp: (record: ClientBatchRecord) => Promise<void>;
}

export const MissingItemsFollowUp: React.FC<MissingItemsFollowUpProps> = ({
  records,
  onDraftFollowUp
}) => {
  const [loadingMap, setLoadingMap] = useState<Record<string, boolean>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const handleGenerateDraft = async (rec: ClientBatchRecord) => {
    setLoadingMap((prev) => ({ ...prev, [rec.id]: true }));
    try {
      await onDraftFollowUp(rec);
    } finally {
      setLoadingMap((prev) => ({ ...prev, [rec.id]: false }));
    }
  };

  const handleCopyText = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-white shadow-xl">
        <h1 className="text-xl font-bold tracking-tight">
          Missing Items Reconciliation & Follow-Up Letter Generator
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Once client organizers or document receipts return, the engine reconciles outstanding items and drafts personalized follow-up reminder emails.
        </p>
      </div>

      {/* Client Missing Items Reconciliation Cards */}
      <div className="space-y-6">
        {records.map((rec) => {
          const outstandingDocs = rec.organizer.flatMap((sec) =>
            sec.requiredDocuments.filter((d) => d.status === 'outstanding').map((d) => d.docName)
          );

          const receivedDocs = rec.organizer.flatMap((sec) =>
            sec.requiredDocuments.filter((d) => d.status === 'received').map((d) => d.docName)
          );

          const isLoading = loadingMap[rec.id];

          return (
            <div
              key={rec.id}
              className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4"
            >
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-4">
                <div>
                  <div className="flex items-center space-x-3">
                    <h2 className="font-bold text-lg text-white">{rec.clientName}</h2>
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase">
                      {rec.segment}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 font-mono mt-0.5">
                    {receivedDocs.length} Documents Received • {outstandingDocs.length} Still Outstanding
                  </p>
                </div>

                <button
                  onClick={() => handleGenerateDraft(rec)}
                  disabled={isLoading}
                  className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-semibold text-xs transition-colors shadow-md shrink-0"
                >
                  {isLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <RefreshCw className="w-4 h-4" />
                  )}
                  <span>Draft AI Follow-Up Letter</span>
                </button>
              </div>

              {/* Outstanding vs Received Columns */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                {/* Received Box */}
                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                  <div className="font-semibold text-emerald-400 flex items-center space-x-1.5">
                    <CheckCircle2 className="w-4 h-4" />
                    <span>Received Documents ({receivedDocs.length})</span>
                  </div>
                  {receivedDocs.length === 0 ? (
                    <p className="text-slate-500 italic">No documents received yet.</p>
                  ) : (
                    <ul className="space-y-1 text-slate-300 font-mono">
                      {receivedDocs.map((doc, idx) => (
                        <li key={idx} className="flex items-center space-x-1.5">
                          <span className="text-emerald-500">•</span>
                          <span>{doc}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* Outstanding Box */}
                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                  <div className="font-semibold text-amber-400 flex items-center space-x-1.5">
                    <Clock className="w-4 h-4" />
                    <span>Outstanding Required Documents ({outstandingDocs.length})</span>
                  </div>
                  {outstandingDocs.length === 0 ? (
                    <p className="text-emerald-400 font-semibold">
                      All required organizer documents received! Ready for tax return preparation.
                    </p>
                  ) : (
                    <ul className="space-y-1 text-slate-300 font-mono">
                      {outstandingDocs.map((doc, idx) => (
                        <li key={idx} className="flex items-center space-x-1.5">
                          <span className="text-amber-500">•</span>
                          <span>{doc}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              {/* Drafted Follow-Up Letter Preview Box */}
              {rec.followUpLetterDraft && (
                <div className="p-4 rounded-xl bg-slate-950 border border-blue-500/30 space-y-3 font-mono text-xs">
                  <div className="flex items-center justify-between text-blue-400 font-sans font-bold">
                    <div className="flex items-center space-x-2">
                      <FileText className="w-4 h-4" />
                      <span>Drafted Client Follow-up Letter</span>
                    </div>
                    <button
                      onClick={() => handleCopyText(rec.id, rec.followUpLetterDraft!)}
                      className="flex items-center space-x-1 text-xs px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors"
                    >
                      {copiedId === rec.id ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                          <span className="text-emerald-400">Copied!</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" />
                          <span>Copy Letter</span>
                        </>
                      )}
                    </button>
                  </div>

                  <p className="whitespace-pre-wrap text-slate-200 leading-relaxed bg-slate-900 p-3 rounded border border-slate-800">
                    {rec.followUpLetterDraft}
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
