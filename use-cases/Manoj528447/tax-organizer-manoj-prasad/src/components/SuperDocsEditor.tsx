import React, { useState } from 'react';
import {
  Sparkles,
  Check,
  X,
  FileCheck2,
  FileText,
  Send,
  Loader2,
  ShieldCheck,
  MessageSquare,
  ChevronDown,
  Info,
  ExternalLink
} from 'lucide-react';
import { ClientBatchRecord, SuperDocsDiff } from '../types';

interface SuperDocsEditorProps {
  selectedClient: ClientBatchRecord;
  onApproveDiff: (diffId: string) => void;
  onRejectDiff: (diffId: string) => void;
  onSendChatEditInstruction: (instruction: string) => Promise<void>;
  onExport: (type: 'organizer' | 'letter') => void;
}

export const SuperDocsEditor: React.FC<SuperDocsEditorProps> = ({
  selectedClient,
  onApproveDiff,
  onRejectDiff,
  onSendChatEditInstruction,
  onExport
}) => {
  const [instructionText, setInstructionText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [viewMode, setViewMode] = useState<'letter' | 'organizer'>('letter');

  const pendingDiffs = selectedClient.diffs.filter((d) => d.status === 'pending');
  const approvedDiffs = selectedClient.diffs.filter((d) => d.status === 'approved');
  const rejectedDiffs = selectedClient.diffs.filter((d) => d.status === 'rejected');

  const handleSendInstruction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!instructionText.trim() || isSubmitting) return;

    setIsSubmitting(true);
    try {
      await onSendChatEditInstruction(instructionText);
      setInstructionText('');
    } catch (err) {
      console.error('Edit instruction error:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Top Client Header & Gate Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-white shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div>
          <div className="flex items-center space-x-3">
            <h1 className="text-xl font-bold tracking-tight">{selectedClient.clientName}</h1>
            <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase">
              {selectedClient.segment}
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            SuperDocs Human-in-the-Loop Diff Gate. Review proposed targeted changes line-by-line before committing.
          </p>
        </div>

        {/* View Switcher & Export Buttons */}
        <div className="flex items-center space-x-3">
          <div className="bg-slate-950 p-1 rounded-xl border border-slate-800 flex text-xs">
            <button
              onClick={() => setViewMode('letter')}
              className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg font-medium transition-colors ${
                viewMode === 'letter'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>Year-End Letter</span>
            </button>
            <button
              onClick={() => setViewMode('organizer')}
              className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg font-medium transition-colors ${
                viewMode === 'organizer'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <FileCheck2 className="w-3.5 h-3.5" />
              <span>Tax Organizer</span>
            </button>
          </div>

          <button
            onClick={() => onExport(viewMode)}
            className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            <span>Export & Print</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Proposed Diffs Gate & Human Review Cards (7 Cols) */}
        <div className="lg:col-span-7 space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center space-x-2">
                <Sparkles className="w-5 h-5 text-amber-300" />
                <h2 className="font-bold text-white text-base">
                  Proposed Targeted Diffs ({pendingDiffs.length} Pending Review)
                </h2>
              </div>
              <div className="text-xs font-mono text-slate-400 flex items-center space-x-2">
                <span className="text-emerald-400 font-semibold">{approvedDiffs.length} Approved</span>
                <span>•</span>
                <span className="text-rose-400 font-semibold">{rejectedDiffs.length} Rejected</span>
              </div>
            </div>

            {selectedClient.diffs.length === 0 ? (
              <div className="text-slate-500 py-8 text-center italic text-sm">
                No proposed diffs in queue. Use the chat instruction panel to request targeted document edits.
              </div>
            ) : (
              <div className="space-y-4">
                {selectedClient.diffs.map((diff) => {
                  const isPending = diff.status === 'pending';
                  const isApproved = diff.status === 'approved';

                  return (
                    <div
                      key={diff.id}
                      className={`rounded-xl border p-4 transition-all ${
                        isPending
                          ? 'bg-slate-950 border-amber-500/40 ring-1 ring-amber-500/20'
                          : isApproved
                          ? 'bg-slate-950/60 border-emerald-500/40'
                          : 'bg-slate-950/40 border-rose-500/30 opacity-60'
                      }`}
                    >
                      {/* Diff Header */}
                      <div className="flex items-center justify-between text-xs mb-3">
                        <div className="flex items-center space-x-2">
                          <span
                            className={`px-2 py-0.5 rounded font-bold uppercase ${
                              diff.changeType === 'addition'
                                ? 'bg-emerald-500/10 text-emerald-400'
                                : diff.changeType === 'modification'
                                ? 'bg-amber-500/10 text-amber-400'
                                : 'bg-rose-500/10 text-rose-400'
                            }`}
                          >
                            {diff.changeType}
                          </span>
                          <span className="font-semibold text-slate-200">{diff.locationLabel}</span>
                        </div>

                        <div className="flex items-center space-x-1 text-[11px] font-mono text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">
                          <Info className="w-3 h-3" />
                          <span>Source: {diff.citation}</span>
                        </div>
                      </div>

                      {/* Side-by-Side Diff Box */}
                      <div className="space-y-2 text-xs font-mono">
                        {diff.originalText && (
                          <div className="p-2.5 rounded bg-rose-950/30 border border-rose-800/40 text-rose-200">
                            <div className="text-[10px] text-rose-400 font-sans uppercase font-bold mb-1">
                              Original (Before Edit)
                            </div>
                            <p className="line-through opacity-80 leading-relaxed">{diff.originalText}</p>
                          </div>
                        )}

                        <div className="p-2.5 rounded bg-emerald-950/30 border border-emerald-800/40 text-emerald-200">
                          <div className="text-[10px] text-emerald-400 font-sans uppercase font-bold mb-1">
                            Proposed Targeted Edit (After)
                          </div>
                          {diff.unmappable ? (
                            <p className="leading-relaxed text-amber-300/90 italic">
                              ⚠ SuperDocs returned this change in an unrecognized format, so its proposed text could not be displayed. The raw response shape is logged to the server console for mapping. (Not approving blind — content unavailable.)
                            </p>
                          ) : (
                            <p className="leading-relaxed whitespace-pre-wrap">{diff.proposedText}</p>
                          )}
                        </div>
                      </div>

                      {/* Explanation */}
                      <p className="mt-2 text-xs text-slate-400 italic">
                        Reasoning: {diff.explanation}
                      </p>

                      {/* Human Review Gate Actions */}
                      <div className="mt-3 pt-3 border-t border-slate-800 flex items-center justify-between">
                        <div className="text-xs">
                          {isPending ? (
                            <span className="text-amber-400 font-semibold">Awaiting CPA Approval</span>
                          ) : isApproved ? (
                            <span className="text-emerald-400 font-semibold flex items-center space-x-1">
                              <Check className="w-3.5 h-3.5" />
                              <span>Approved & Committed</span>
                            </span>
                          ) : (
                            <span className="text-rose-400 font-semibold flex items-center space-x-1">
                              <X className="w-3.5 h-3.5" />
                              <span>Rejected</span>
                            </span>
                          )}
                        </div>

                        {isPending && (
                          <div className="flex items-center space-x-2">
                            <button
                              onClick={() => onRejectDiff(diff.id)}
                              className="flex items-center space-x-1 px-3 py-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-xs font-medium transition-colors"
                            >
                              <X className="w-3.5 h-3.5" />
                              <span>Reject</span>
                            </button>
                            <button
                              onClick={() => onApproveDiff(diff.id)}
                              className="flex items-center space-x-1 px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-md transition-colors"
                            >
                              <Check className="w-3.5 h-3.5" />
                              <span>Approve Diff</span>
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* SuperDocs Chat Edit Instruction Prompt Box */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex items-center space-x-2">
              <MessageSquare className="w-5 h-5 text-blue-400" />
              <h2 className="font-bold text-white text-base">SuperDocs Targeted Chat Edit Instruction</h2>
            </div>
            <p className="text-xs text-slate-400">
              Instruct the SuperDocs agent to modify specific tax law paragraphs or organizer requirements. The agent will respond with itemized targeted diffs for your review.
            </p>

            <form onSubmit={handleSendInstruction} className="space-y-3">
              <textarea
                value={instructionText}
                onChange={(e) => setInstructionText(e.target.value)}
                placeholder='e.g. "Add a specific note about Section 179 equipment purchases exceeding $50k in 2025" or "Request 1099-K documentation for online platform sales"'
                rows={3}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={!instructionText.trim() || isSubmitting}
                  className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-semibold text-xs shadow-md transition-all"
                >
                  {isSubmitting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                  <span>Send Targeted Instruction</span>
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* Right Column: Live Document Preview (5 Cols) */}
        <div className="lg:col-span-5 space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4 sticky top-24">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h2 className="font-bold text-white text-base">
                Live Document Grounded Preview ({viewMode === 'letter' ? 'Year-End Letter' : 'Organizer'})
              </h2>
              <span className="text-xs font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                Grounded 2024 Sources
              </span>
            </div>

            {viewMode === 'letter' ? (
              /* Year-End Letter Preview */
              <div className="bg-white text-slate-900 p-6 rounded-xl space-y-4 text-xs font-serif shadow-inner max-h-[600px] overflow-y-auto">
                <div className="font-bold text-sm border-b pb-2">
                  {selectedClient.yearEndLetter.clientName}
                </div>
                <p className="font-semibold">{selectedClient.yearEndLetter.greeting}</p>
                <p className="leading-relaxed text-slate-700">
                  {selectedClient.yearEndLetter.overview}
                </p>

                <div className="space-y-3 my-4">
                  <div className="text-xs font-sans font-bold text-blue-900 uppercase tracking-wider">
                    Applicable Tax Law Changes:
                  </div>
                  {selectedClient.yearEndLetter.personalizedLawParagraphs.map((law, idx) => (
                    <div key={idx} className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1 font-sans">
                      <div className="font-bold text-slate-900">{law.lawTitle}</div>
                      <div className="text-[11px] text-slate-600">{law.relevanceReason}</div>
                      <div className="text-[11px] text-blue-800 font-medium">Impact: {law.estimatedImpact}</div>
                      <div className="text-[11px] text-amber-800 font-semibold">Action: {law.actionItem}</div>
                    </div>
                  ))}
                </div>

                {selectedClient.yearEndLetter.appliedEdits && selectedClient.yearEndLetter.appliedEdits.length > 0 && (
                  <div className="space-y-2 mt-2">
                    <div className="text-xs font-sans font-bold text-emerald-800 uppercase tracking-wider">
                      Approved Edits (applied via human-gate review):
                    </div>
                    {selectedClient.yearEndLetter.appliedEdits.map((edit, idx) => (
                      <div key={idx} className="p-3 bg-emerald-50 rounded-lg border border-emerald-200 text-[11px] text-emerald-900 font-sans whitespace-pre-line">
                        {edit}
                      </div>
                    ))}
                  </div>
                )}

                <p className="text-slate-600 italic">
                  {selectedClient.yearEndLetter.filingDeadlineNotice}
                </p>
                <p className="whitespace-pre-line font-medium text-slate-800">
                  {selectedClient.yearEndLetter.closing}
                </p>
              </div>
            ) : (
              /* Organizer Summary Preview */
              <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-4 text-xs max-h-[600px] overflow-y-auto">
                <div className="font-bold text-sm text-white">
                  Pre-filled Tax Organizer Schedules
                </div>

                {selectedClient.organizer.map((sec) => (
                  <div key={sec.id} className="p-3 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
                    <h3 className="font-semibold text-blue-400">{sec.sectionTitle}</h3>
                    <div className="space-y-1.5">
                      {sec.requiredDocuments.map((doc) => (
                        <div key={doc.id} className="flex items-center justify-between text-[11px] p-2 bg-slate-950 rounded border border-slate-800">
                          <div>
                            <div className="text-slate-200 font-medium">{doc.docName}</div>
                            <div className="text-slate-500 font-mono">Source: {doc.sourceCitation}</div>
                          </div>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                              doc.status === 'received'
                                ? 'bg-emerald-500/20 text-emerald-300'
                                : 'bg-amber-500/20 text-amber-300'
                            }`}
                          >
                            {doc.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
