import React from 'react';
import {
  CheckCircle2,
  Clock,
  Upload,
  FileText,
  AlertCircle,
  HelpCircle,
  ShieldCheck,
  Check,
  X
} from 'lucide-react';
import { ClientBatchRecord, PreFilledOrganizerSection } from '../types';

interface FillableOrganizerViewProps {
  client: ClientBatchRecord;
  onUpdateDocStatus: (docId: string, status: 'received' | 'outstanding' | 'waived', fileName?: string) => void;
  onExport: () => void;
}

export const FillableOrganizerView: React.FC<FillableOrganizerViewProps> = ({
  client,
  onUpdateDocStatus,
  onExport
}) => {
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-white shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div>
          <div className="flex items-center space-x-3">
            <h1 className="text-xl font-bold tracking-tight">
              Fillable Tax Organizer: {client.clientName}
            </h1>
            <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase">
              {client.segment}
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Pre-filled directly from 2024 return. Only showing schedules and checklists applicable to this client segment.
          </p>
        </div>

        <button
          onClick={onExport}
          className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs transition-colors shadow-md"
        >
          <Upload className="w-3.5 h-3.5" />
          <span>Export Print / Fillable PDF</span>
        </button>
      </div>

      {/* Sections List */}
      <div className="space-y-6">
        {client.organizer.map((sec: PreFilledOrganizerSection) => (
          <div
            key={sec.id}
            className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4"
          >
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h2 className="font-bold text-white text-base text-blue-400">
                {sec.sectionTitle}
              </h2>
              <span className="text-xs font-mono text-slate-400 capitalize">
                Category: {sec.category}
              </span>
            </div>

            {/* Documents Checklist */}
            <div className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Required Tax Forms & Receipts Checklist
              </h3>

              <div className="space-y-2">
                {sec.requiredDocuments.map((doc) => {
                  const isReceived = doc.status === 'received';
                  const isWaived = doc.status === 'waived';

                  return (
                    <div
                      key={doc.id}
                      className={`p-4 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-all ${
                        isReceived
                          ? 'bg-slate-950/80 border-emerald-500/40'
                          : isWaived
                          ? 'bg-slate-950/40 border-slate-800 opacity-60'
                          : 'bg-slate-950 border-amber-500/30'
                      }`}
                    >
                      <div className="space-y-1">
                        <div className="flex items-center space-x-2">
                          <span className="font-semibold text-sm text-white">{doc.docName}</span>
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                            Grounded: {doc.sourceCitation}
                          </span>
                        </div>
                        {doc.priorYearValue && (
                          <div className="text-xs text-slate-400">
                            2024 Prior Value: <span className="text-slate-200 font-mono">{doc.priorYearValue}</span>
                          </div>
                        )}
                        {doc.receivedFileName && (
                          <div className="text-xs text-emerald-400 flex items-center space-x-1">
                            <FileText className="w-3 h-3" />
                            <span>Received File: {doc.receivedFileName} ({doc.receivedDate})</span>
                          </div>
                        )}
                      </div>

                      {/* Status Toggle Buttons */}
                      <div className="flex items-center space-x-2 shrink-0">
                        <button
                          onClick={() => onUpdateDocStatus(doc.id, 'received', 'Uploaded_Tax_Form.pdf')}
                          className={`flex items-center space-x-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                            isReceived
                              ? 'bg-emerald-600 text-white shadow-sm'
                              : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                          }`}
                        >
                          <Check className="w-3.5 h-3.5" />
                          <span>Received</span>
                        </button>

                        <button
                          onClick={() => onUpdateDocStatus(doc.id, 'outstanding')}
                          className={`flex items-center space-x-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                            doc.status === 'outstanding'
                              ? 'bg-amber-600 text-white shadow-sm'
                              : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                          }`}
                        >
                          <Clock className="w-3.5 h-3.5" />
                          <span>Outstanding</span>
                        </button>

                        <button
                          onClick={() => onUpdateDocStatus(doc.id, 'waived')}
                          className={`flex items-center space-x-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                            isWaived
                              ? 'bg-slate-600 text-white shadow-sm'
                              : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                          }`}
                        >
                          <X className="w-3.5 h-3.5" />
                          <span>Waive</span>
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Pre-filled Questions */}
            {sec.questions.length > 0 && (
              <div className="space-y-3 pt-3 border-t border-slate-800">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Pre-filled Questionnaire & Disclosures
                </h3>
                <div className="space-y-2">
                  {sec.questions.map((q) => (
                    <div key={q.id} className="p-3 bg-slate-950 rounded-xl border border-slate-800 space-y-1 text-xs">
                      <div className="font-semibold text-slate-200">{q.questionText}</div>
                      <div className="text-slate-400 font-mono">
                        Prior Year Answer: <span className="text-blue-400">{q.priorYearAnswer}</span> (Source: {q.sourceCitation})
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
