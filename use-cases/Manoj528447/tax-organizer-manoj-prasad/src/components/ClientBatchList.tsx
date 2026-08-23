import React, { useState } from 'react';
import {
  Building2,
  Home,
  Globe2,
  User,
  Crown,
  FileCheck2,
  FileText,
  Sparkles,
  ChevronRight,
  Filter,
  CheckCircle,
  AlertTriangle,
  Play,
  Printer,
  Download
} from 'lucide-react';
import { ClientBatchRecord, ClientSegment } from '../types';

interface ClientBatchListProps {
  records: ClientBatchRecord[];
  onSelectClient: (record: ClientBatchRecord, tab: 'organizer' | 'letter' | 'diffs') => void;
  onRunBatch: () => void;
  onOpenUpload: () => void;
}

export const ClientBatchList: React.FC<ClientBatchListProps> = ({
  records,
  onSelectClient,
  onRunBatch,
  onOpenUpload
}) => {
  const [selectedSegment, setSelectedSegment] = useState<string>('all');

  const filteredRecords = records.filter(
    (r) => selectedSegment === 'all' || r.segment === selectedSegment
  );

  const getSegmentBadge = (segment: ClientSegment) => {
    switch (segment) {
      case 'business':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <Building2 className="w-3 h-3" />
            <span>Business / S-Corp</span>
          </span>
        );
      case 'rental':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <Home className="w-3 h-3" />
            <span>Rental Property</span>
          </span>
        );
      case 'expatriate':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <Globe2 className="w-3 h-3" />
            <span>Expatriate / Overseas</span>
          </span>
        );
      case 'hnw':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <Crown className="w-3 h-3" />
            <span>High Net Worth</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap bg-slate-500/10 text-slate-300 border border-slate-500/20">
            <User className="w-3 h-3" />
            <span>Individual</span>
          </span>
        );
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header & Filter Controls */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-white shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Client Tax Organizer & Year-End Letter Batch</h1>
          <p className="text-sm text-slate-400 mt-1">
            Pre-filled from 2024 returns with grounded line citations, personalized 2025 tax law updates, and SuperDocs human gate review.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Segment Filter */}
          <div className="flex flex-wrap items-center gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs">
            <Filter className="w-3.5 h-3.5 text-slate-400 ml-2 mr-1" />
            {['all', 'business', 'rental', 'expatriate', 'hnw', 'individual'].map((seg) => (
              <button
                key={seg}
                onClick={() => setSelectedSegment(seg)}
                className={`px-2.5 py-1.5 rounded-lg capitalize font-medium transition-colors ${
                  selectedSegment === seg
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                }`}
              >
                {seg}
              </button>
            ))}
          </div>

          <button
            onClick={onRunBatch}
            className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-semibold text-xs sm:text-sm shadow-md transition-all"
          >
            <Play className="w-4 h-4 fill-current" />
            <span>Generate Batch</span>
          </button>
        </div>
      </div>

      {/* Batch Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredRecords.map((record) => {
          const pendingDiffsCount = record.diffs.filter((d) => d.status === 'pending').length;
          const approvedDiffsCount = record.diffs.filter((d) => d.status === 'approved').length;

          return (
            <div
              key={record.id}
              className="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-2xl p-5 shadow-lg transition-all flex flex-col justify-between space-y-4 group"
            >
              <div className="space-y-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-1 min-w-0">
                    <h3 className="font-bold text-base text-white group-hover:text-blue-400 transition-colors">
                      {record.clientName}
                    </h3>
                    {record.clientName === 'Unidentified Client' && record.priorReturn.sourceFileName && (
                      <p className="text-xs text-amber-400/80 truncate max-w-[220px]" title={record.priorReturn.sourceFileName}>
                        No client name found -- source: {record.priorReturn.sourceFileName}
                      </p>
                    )}
                    <p className="text-xs text-slate-400 font-mono">
                      SSN/EIN: **-{record.priorReturn.ssnEinLast4} | {record.priorReturn.filingStatus}
                    </p>
                  </div>
                  <div className="shrink-0">
                    {getSegmentBadge(record.segment)}
                  </div>
                </div>

                {/* AI extraction fallback notice. When Gemini couldn't extract
                    (network/auth/quota), the record is a generic organizer --
                    say so plainly here so it's never mistaken for a real-but-thin
                    extraction. Honest "never bluffs" surfacing of the reason. */}
                {record.priorReturn.extractionNotice && (
                  <div className="flex items-start gap-2 bg-amber-500/10 border border-amber-500/30 rounded-xl p-2.5 text-[11px] text-amber-200 leading-snug">
                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-400" />
                    <span>
                      <span className="font-semibold">AI extraction unavailable</span> — {record.priorReturn.extractionNotice.message}
                    </span>
                  </div>
                )}

                {/* Prior Return Grounding Info */}
                <div className="bg-slate-950 p-3 rounded-xl border border-slate-800/80 space-y-1.5 text-xs">
                  <div className="text-slate-400 font-medium flex items-center justify-between">
                    <span>Prior Schedules Applied:</span>
                    <span className="text-blue-400 font-mono font-semibold">
                      {record.priorReturn.taxYear} Return
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {record.priorReturn.schedulesApplied.map((sched, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px] font-mono border border-slate-700"
                      >
                        {sched}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Missing vs Received Progress */}
                <div className="space-y-1">
                  <div className="flex justify-between text-xs text-slate-400">
                    <span>Organizer Documents Status:</span>
                    <span className="font-mono text-slate-200">
                      {record.receivedItemsCount} Received / {record.missingItemsCount} Missing
                    </span>
                  </div>
                  <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                    <div
                      className="bg-emerald-500 h-full transition-all"
                      style={{
                        width: `${
                          (record.receivedItemsCount /
                            (record.receivedItemsCount + record.missingItemsCount || 1)) *
                          100
                        }%`
                      }}
                    />
                  </div>
                </div>

                {/* SuperDocs Diff Gate Status Pill */}
                <div className="flex items-center justify-between pt-1">
                  <div className="flex items-center space-x-2">
                    {pendingDiffsCount > 0 ? (
                      <span className="inline-flex items-center space-x-1 text-xs px-2.5 py-1 rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/20 font-medium">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        <span>{pendingDiffsCount} SuperDocs Diffs Pending</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center space-x-1 text-xs px-2.5 py-1 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                        <CheckCircle className="w-3.5 h-3.5" />
                        <span>{approvedDiffsCount} Diffs Approved</span>
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="grid grid-cols-3 gap-2 border-t border-slate-800/80 pt-3 text-xs">
                <button
                  onClick={() => onSelectClient(record, 'organizer')}
                  className="flex items-center justify-center space-x-1 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium transition-colors"
                >
                  <FileCheck2 className="w-3.5 h-3.5 text-blue-400" />
                  <span>Organizer</span>
                </button>

                <button
                  onClick={() => onSelectClient(record, 'letter')}
                  className="flex items-center justify-center space-x-1 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium transition-colors"
                >
                  <FileText className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Letter</span>
                </button>

                <button
                  onClick={() => onSelectClient(record, 'diffs')}
                  className="flex items-center justify-center space-x-1 py-2 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 font-medium transition-colors"
                >
                  <Sparkles className="w-3.5 h-3.5 text-amber-300" />
                  <span>Diff Gate</span>
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
