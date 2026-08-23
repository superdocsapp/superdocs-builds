import React from 'react';
import { FileText, Printer, Download, Sparkles, BookOpen, AlertCircle } from 'lucide-react';
import { ClientBatchRecord } from '../types';

interface YearEndLetterViewProps {
  client: ClientBatchRecord;
  onExport: () => void;
}

export const YearEndLetterView: React.FC<YearEndLetterViewProps> = ({ client, onExport }) => {
  const { yearEndLetter } = client;

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Top Controls Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-white shadow-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            Personalized Year-End Tax Law Letter
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Client: <span className="text-blue-400 font-semibold">{client.clientName}</span> | Segment: <span className="uppercase text-slate-200">{client.segment}</span>
          </p>
        </div>

        <button
          onClick={onExport}
          className="flex items-center space-x-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-semibold text-xs sm:text-sm shadow-md transition-all"
        >
          <Printer className="w-4 h-4" />
          <span>Print / Export Letter</span>
        </button>
      </div>

      {/* High-Fidelity Printable Letter Layout */}
      <div className="bg-white text-slate-900 rounded-2xl p-8 sm:p-12 shadow-2xl border border-slate-200 space-y-6 font-serif">
        {/* Letterhead */}
        <div className="border-b-2 border-slate-900 pb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 font-sans">
          <div>
            <div className="text-xl font-bold tracking-tight text-slate-900">
              PREMIER CPA & TAX ADVISORY GROUP
            </div>
            <div className="text-xs text-slate-600">
              Tax Planning & Compliance Services • 100 Financial Center Blvd, Suite 400
            </div>
          </div>
          <div className="text-xs font-mono text-slate-500 sm:text-right">
            <div>Tax Year: 2025 Planning</div>
            <div>Date: January 2026</div>
          </div>
        </div>

        {/* Client Address Block */}
        <div className="font-sans text-xs text-slate-800 space-y-0.5 pt-2">
          <div className="font-bold text-sm text-slate-900">{yearEndLetter.clientName}</div>
          <div>Tax Record ID: {client.clientId}</div>
          <div>Filing Category: {client.priorReturn.filingStatus}</div>
        </div>

        {/* Salutation */}
        <div className="font-semibold text-sm text-slate-900 pt-2">
          {yearEndLetter.greeting}
        </div>

        {/* Overview Paragraph */}
        <p className="text-xs leading-relaxed text-slate-800">
          {yearEndLetter.overview}
        </p>

        {/* Tailored Law Update Paragraphs */}
        <div className="space-y-4 my-6 font-sans">
          <div className="text-xs font-bold text-blue-900 uppercase tracking-wider border-b border-blue-200 pb-1">
            2025 Tax Law Changes Relevant to Your Tax Profile
          </div>

          {yearEndLetter.personalizedLawParagraphs.map((law, idx) => (
            <div
              key={idx}
              className="p-4 bg-slate-50 rounded-xl border border-slate-200 space-y-2 text-xs"
            >
              <div className="font-bold text-sm text-slate-900 flex items-center space-x-2">
                <BookOpen className="w-4 h-4 text-blue-600 shrink-0" />
                <span>{law.lawTitle}</span>
              </div>

              <p className="text-slate-700 leading-relaxed">
                <strong className="text-slate-900">Why this applies to you:</strong> {law.relevanceReason}
              </p>

              <div className="p-2.5 rounded bg-blue-50/80 border border-blue-100 text-blue-950 font-medium">
                <strong>Estimated Impact:</strong> {law.estimatedImpact}
              </div>

              <div className="p-2.5 rounded bg-amber-50/80 border border-amber-200 text-amber-950 font-semibold">
                <strong>Required Action Item:</strong> {law.actionItem}
              </div>
            </div>
          ))}
        </div>

        {/* Deadline Notice */}
        <div className="p-4 rounded-xl bg-slate-100 border border-slate-200 font-sans text-xs text-slate-800 space-y-1">
          <div className="font-bold text-slate-900 flex items-center space-x-1.5">
            <AlertCircle className="w-4 h-4 text-amber-600" />
            <span>Filing Deadline & Organizer Notice</span>
          </div>
          <p>{yearEndLetter.filingDeadlineNotice}</p>
        </div>

        {/* Closing */}
        <div className="pt-6 font-sans text-xs text-slate-800 space-y-4">
          <p className="whitespace-pre-line leading-relaxed font-medium">
            {yearEndLetter.closing}
          </p>
          <div className="pt-4 border-t border-slate-200 text-[10px] text-slate-500 italic">
            SuperDocs AI Grounded Tax Engine • Verified against 2024 Form 1040
            {client.priorReturn.schedulesApplied.length > 0
              ? ` & ${client.priorReturn.schedulesApplied.join(', ')} filings.`
              : ' filings.'}
          </div>
        </div>
      </div>
    </div>
  );
};
