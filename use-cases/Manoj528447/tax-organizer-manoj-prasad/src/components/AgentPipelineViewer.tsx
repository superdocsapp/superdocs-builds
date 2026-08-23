import React from 'react';
import {
  Play,
  Pause,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  Clock,
  DollarSign,
  Info,
  ShieldAlert,
  ArrowRight,
  Database
} from 'lucide-react';
import { BatchRunCheckpoint, AgentStage } from '../types';
import { ArchitectureDiagram } from './ArchitectureDiagram';

interface AgentPipelineViewerProps {
  checkpoint: BatchRunCheckpoint;
  onRunStage: (stage: AgentStage) => void;
  onRunAll: () => void;
  onReset: () => void;
  onApproveAllRemaining: (status?: 'approved' | 'rejected') => void;
}

const STAGES_FLOW: { stage: AgentStage; title: string; description: string }[] = [
  {
    stage: 'INGEST_PRIOR_RETURN',
    title: '1. Ingest Prior Return',
    description: 'Extracts Schedule C/E/2555 & Line citations from 2024 returns.'
  },
  {
    stage: 'CLASSIFY_SEGMENT',
    title: '2. Classify Segment',
    description: 'Categorizes clients into Business, Rental, Expatriate, HNW, or Individual.'
  },
  {
    stage: 'MATCH_LAW_UPDATES',
    title: '3. Match Law Updates',
    description: 'Matches 2025 IRC tax updates (QBI, §179, FEIE) to client profile.'
  },
  {
    stage: 'GENERATE_DRAFT_BATCH',
    title: '4. Generate Draft Batch',
    description: 'Pre-fills organizers & drafts personalized year-end tax law letters.'
  },
  {
    stage: 'SUPERDOCS_DIFF_GATE',
    title: '5. SuperDocs Diff Gate',
    description: 'Presents itemized proposed changes for CPA human review & approval.'
  },
  {
    stage: 'EXECUTE_APPROVALS',
    title: '6. Execute Approvals',
    description: 'Surgically commits approved diffs while preserving untouched sections.'
  },
  {
    stage: 'TRACK_MISSING_ITEMS',
    title: '7. Track Missing Items',
    description: 'Reconciles returned client files against organizer requirements.'
  },
  {
    stage: 'DRAFT_FOLLOWUP',
    title: '8. Draft Follow-up',
    description: 'Generates tailored missing-items follow-up reminder letters.'
  }
];

export const AgentPipelineViewer: React.FC<AgentPipelineViewerProps> = ({
  checkpoint,
  onRunStage,
  onRunAll,
  onReset,
  onApproveAllRemaining
}) => {
  // How many diffs across the whole batch still block the review gate, and
  // which clients they belong to. The gate is batch-wide but the review UI is
  // per-client, so surfacing this here is what makes "why is it stuck at 5?"
  // answerable at a glance instead of by clicking Run and watching runtime climb.
  const clientsWithPending = checkpoint.clientRecords.filter((c) =>
    c.diffs.some((d) => d.status === 'pending')
  );
  const totalPendingDiffs = clientsWithPending.reduce(
    (acc, c) => acc + c.diffs.filter((d) => d.status === 'pending').length,
    0
  );
  const gateIsHolding = totalPendingDiffs > 0;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Top Banner: Status, Checkpoint state & Cost/Time metrics */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-white shadow-xl flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6">
        <div className="space-y-1 min-w-0 lg:max-w-md">
          <div className="flex items-center flex-wrap gap-x-3 gap-y-2">
            <h1 className="text-xl font-bold tracking-tight">SuperDocs Agentic Execution Engine</h1>
            <span
              className={`px-3 py-1 rounded-full text-xs font-semibold whitespace-nowrap ${
                checkpoint.currentStage === 'SUPERDOCS_DIFF_GATE'
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                  : checkpoint.currentStage === 'COMPLETED'
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                  : 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
              }`}
            >
              Stage: {checkpoint.currentStage}
            </span>
          </div>
          <p className="text-sm text-slate-400">
            Visible stage machine with checkpoint resilience, grounded line citations, and human gate review.
          </p>
        </div>

        {/* Action Controls & Checkpoint Metrics */}
        <div className="flex flex-wrap items-center gap-3 lg:justify-end lg:shrink-0">
          <button
            onClick={onRunAll}
            className="flex items-center space-x-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-semibold text-sm shadow-lg shadow-blue-500/20 transition-all"
          >
            <Play className="w-4 h-4 fill-current" />
            <span>Run Full Pipeline</span>
          </button>

          {gateIsHolding && (
            <button
              onClick={() => onApproveAllRemaining('approved')}
              title={`Approve the ${totalPendingDiffs} pending diff(s) still holding the gate, across ${clientsWithPending.length} client(s)`}
              className="flex items-center space-x-2 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-sm shadow-lg shadow-emerald-500/20 transition-all"
            >
              <CheckCircle2 className="w-4 h-4" />
              <span>Approve all remaining ({totalPendingDiffs})</span>
            </button>
          )}

          <button
            onClick={onReset}
            className="flex items-center space-x-2 px-3.5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium text-sm border border-slate-700 transition-colors"
          >
            <RotateCcw className="w-4 h-4" />
            <span>Reset Run</span>
          </button>

          <div className="flex items-center space-x-4 bg-slate-950 px-4 py-2 rounded-xl border border-slate-800 font-mono text-xs">
            <div>
              <div className="text-slate-500 text-[10px] uppercase font-sans">Token Cost</div>
              <div className="text-emerald-400 font-bold">${checkpoint.totalCostEstimate.toFixed(4)}</div>
            </div>
            <div className="h-6 w-px bg-slate-800" />
            <div>
              <div className="text-slate-500 text-[10px] uppercase font-sans">Runtime</div>
              <div className="text-amber-400 font-bold">{(checkpoint.totalDurationMs / 1000).toFixed(2)}s</div>
            </div>
            <div className="h-6 w-px bg-slate-800" />
            <div>
              <div className="text-slate-500 text-[10px] uppercase font-sans">Checkpoint State</div>
              <div className="text-blue-400 font-bold flex items-center space-x-1">
                <Database className="w-3 h-3" />
                <span>SAVED</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Human-review gate status banner. The gate is batch-wide: EVERY client's
          diffs must be decided before the pipeline can advance past stage 5.
          Because the review UI is per-client, this banner names exactly which
          clients are still holding the gate, so "stuck at stage 5" is never a
          silent mystery. */}
      {gateIsHolding && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-2xl p-5 text-amber-100 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start space-x-3">
            <ShieldAlert className="w-5 h-5 text-amber-400 mt-0.5 shrink-0" />
            <div className="space-y-1">
              <p className="font-semibold text-amber-200">
                Review gate is holding — {totalPendingDiffs} diff(s) across {clientsWithPending.length} client(s) still need a decision.
              </p>
              <p className="text-sm text-amber-100/80">
                The gate is batch-wide: the pipeline stays at stage 5 until every client's diffs are approved or rejected. Still pending:{' '}
                <span className="font-medium">
                  {clientsWithPending
                    .map((c) => `${c.clientName} (${c.diffs.filter((d) => d.status === 'pending').length})`)
                    .join(', ')}
                </span>
                . Decide each client in the SuperDocs Diff Gate, or clear them all here.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => onApproveAllRemaining('approved')}
              className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-sm transition-colors"
            >
              <CheckCircle2 className="w-4 h-4" />
              <span>Approve all remaining</span>
            </button>
          </div>
        </div>
      )}

      {/* Stage Execution Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {STAGES_FLOW.map((s) => {
          const isCurrent = checkpoint.currentStage === s.stage;
          const isDone = checkpoint.completedStages.includes(s.stage);

          return (
            <div
              key={s.stage}
              className={`p-4 rounded-xl border transition-all ${
                isCurrent
                  ? 'bg-slate-900 border-blue-500/80 ring-2 ring-blue-500/20 shadow-lg'
                  : isDone
                  ? 'bg-slate-900/60 border-emerald-500/30 text-slate-200'
                  : 'bg-slate-900/40 border-slate-800/80 text-slate-400'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center space-x-2">
                  {isDone ? (
                    <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                  ) : isCurrent ? (
                    <div className="w-5 h-5 rounded-full border-2 border-blue-400 border-t-transparent animate-spin shrink-0" />
                  ) : (
                    <div className="w-5 h-5 rounded-full border-2 border-slate-700 shrink-0" />
                  )}
                  <h3 className="font-semibold text-sm text-slate-100">{s.title}</h3>
                </div>
                <button
                  onClick={() => onRunStage(s.stage)}
                  className="p-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors"
                  title="Run stage directly"
                >
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
              <p className="mt-2 text-xs text-slate-400 leading-relaxed">{s.description}</p>
            </div>
          );
        })}
      </div>

      {/* Agent Activity Logs Stream */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center space-x-2">
            <Clock className="w-4 h-4 text-blue-400" />
            <h2 className="font-semibold text-white text-base">Execution Audit Trail & Decisions Log</h2>
          </div>
          <span className="text-xs text-slate-400 font-mono">
            {checkpoint.logs.length} Event Logs Recorded
          </span>
        </div>

        <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/80 font-mono text-xs space-y-2 max-h-80 overflow-y-auto">
          {checkpoint.logs.length === 0 ? (
            <div className="text-slate-500 italic py-4 text-center">No logs generated yet.</div>
          ) : (
            checkpoint.logs.map((log, index) => (
              <div key={index} className="flex items-start space-x-3 py-1 border-b border-slate-900 last:border-0">
                <span className="text-slate-500 shrink-0">{log.timestamp}</span>
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase shrink-0 ${
                    log.level === 'success'
                      ? 'bg-emerald-500/10 text-emerald-400'
                      : log.level === 'warn'
                      ? 'bg-amber-500/10 text-amber-400'
                      : log.level === 'error'
                      ? 'bg-rose-500/10 text-rose-400'
                      : 'bg-blue-500/10 text-blue-400'
                  }`}
                >
                  {log.stage}
                </span>
                <span className="text-slate-200 flex-1 leading-relaxed">{log.message}</span>
                {log.costDelta ? (
                  <span className="text-emerald-400 text-[10px] shrink-0">
                    +${log.costDelta.toFixed(4)}
                  </span>
                ) : null}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Architecture & REST Flow Diagram */}
      <ArchitectureDiagram />
    </div>
  );
};
