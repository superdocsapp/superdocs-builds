import { useState, useMemo, useCallback, useEffect } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  BackgroundVariant,
  Position,
  applyNodeChanges,
} from '@xyflow/react';
import type { Node, Edge, NodeChange } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { PipelineNode } from '@/components/pipeline/PipelineNode';
import { MergeNode } from '@/components/pipeline/MergeNode';
import { AddNode } from '@/components/pipeline/AddNode';
import { SmoothEdge } from '@/components/pipeline/SmoothEdge';
import { NodeDetailPanel } from '@/components/pipeline/NodeDetailPanel';
import { PendingReviewPanel } from '@/components/pipeline/PendingReviewPanel';
import { DeliverablePanel } from '@/components/pipeline/DeliverablePanel';
import { FindingsPanel } from '@/components/pipeline/FindingsPanel';
import { ReportPanel } from '@/components/pipeline/ReportPanel';
import { usePipelineState } from '@/hooks/usePipelineState';
import { applyDagreLayout } from '@/utils/pipelineLayout';
import { fetchPipelineRuns, fetchRunCost, fetchRunHistory, resumeRun, deleteRun } from '@/services/pipelineApi';
import type { RunListItem, PileListItem, SeedDemoResponse } from '@/services/pipelineApi';
import { fetchPileDetail, startPipelineWithPile } from '@/services/pipelineApi';
import { ResumeButton } from '@/components/review/ResumeButton';
import { PilesPanel } from '@/components/pipeline/PilesPanel';
import type { NodeStatus, EdgeDecision } from '@/types/pipeline';

// ─── Sidebar ─────────────────────────────────────────────────────────────────

// ─── Custom Checkbox ─────────────────────────────────────────────────────────

function CustomCheckbox({ checked, onChange, label }: { checked: boolean; onChange: () => void; label: string }) {
  return (
    <label className="group flex items-center gap-2.5 px-2 py-1.5 -mx-2 rounded-md cursor-pointer hover:bg-white/[0.04] transition-colors">
      <button
        role="checkbox"
        aria-checked={checked}
        onClick={onChange}
        className={`
          flex items-center justify-center w-4 h-4 rounded border transition-all duration-150
          ${checked
            ? 'bg-indigo-500 border-indigo-500 shadow-sm shadow-indigo-500/30'
            : 'border-white/25 bg-white/[0.04] group-hover:border-white/40'
          }
        `}
      >
        {checked && (
          <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
            <path d="M2.5 6l2.5 2.5 4.5-5" />
          </svg>
        )}
      </button>
      <span className={`text-[13px] transition-colors ${checked ? 'text-white/90' : 'text-white/60 group-hover:text-white/80'}`}>
        {label}
      </span>
    </label>
  );
}

// ─── Collapsible Filter Section ──────────────────────────────────────────────

function FilterSection({ title, defaultOpen = true, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full py-1.5 group"
      >
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/45 group-hover:text-white/60 transition-colors">
          {title}
        </span>
        <svg
          className={`w-3 h-3 text-white/30 group-hover:text-white/50 transition-all duration-200 ${open ? '' : '-rotate-90'}`}
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
        >
          <path d="M3 4.5l3 3 3-3" />
        </svg>
      </button>
      {open && (
        <div className="mt-1.5 space-y-0.5">
          {children}
        </div>
      )}
    </div>
  );
}

// ─── Sidebar ─────────────────────────────────────────────────────────────────

const STATUS_DOT_COLOR: Record<string, string> = {
  running: 'bg-indigo-400',
  completed: 'bg-emerald-400',
  failed: 'bg-rose-400',
  paused: 'bg-amber-400',
  cancelled: 'bg-amber-400',
  pending: 'bg-white/40',
};

function Sidebar({ collapsed, onToggle, runs, activeRunId, onRunSelect, onRunDelete, selectedPileId, onPileSelect, onDocumentsUploaded, onDemoSeeded }: {
  collapsed: boolean;
  onToggle: () => void;
  runs: RunListItem[];
  activeRunId: string | null;
  onRunSelect: (run: RunListItem) => void;
  onRunDelete: (runId: string) => void;
  selectedPileId: string | null;
  onPileSelect: (pile: PileListItem) => void;
  onDocumentsUploaded: () => void;
  onDemoSeeded: (result: SeedDemoResponse) => Promise<void>;
}) {
  // Local checkbox state (filter state — purely UI for now)
  const [statusFilters, setStatusFilters] = useState<Record<string, boolean>>({});
  const [docTypeFilters, setDocTypeFilters] = useState<Record<string, boolean>>({});
  const [playbookFilters, setPlaybookFilters] = useState<Record<string, boolean>>({});

  const toggle = (setter: React.Dispatch<React.SetStateAction<Record<string, boolean>>>, key: string) => {
    setter((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div
      className={`h-full border-r border-white/[0.06] bg-[#0f1320] transition-all duration-200 flex flex-col ${
        collapsed ? 'w-12' : 'w-72'
      }`}
    >
      <button
        onClick={onToggle}
        className="flex items-center justify-center h-10 w-full border-b border-white/[0.06] text-white/50 hover:text-white/80 hover:bg-white/[0.03] transition-colors"
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <svg className={`w-4 h-4 transition-transform ${collapsed ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
      </button>

      {collapsed ? null : (
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
          {/* Search */}
          <div className="relative">
            <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-white/30 pointer-events-none" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5}>
              <circle cx="7" cy="7" r="5" />
              <path d="M11 11l3.5 3.5" strokeLinecap="round" />
            </svg>
            <input
              type="text"
              placeholder="Search runs..."
              className="w-full rounded-lg border border-white/[0.08] bg-white/[0.03] pl-8 pr-3 py-2 text-[13px] text-white/80 placeholder-white/30 transition-all focus:border-indigo-500/60 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:bg-white/[0.05] hover:border-white/[0.15]"
            />
          </div>

          {/* Piles */}
          <PilesPanel
            selectedPileId={selectedPileId}
            onPileSelect={onPileSelect}
            onDocumentsUploaded={onDocumentsUploaded}
            onDemoSeeded={onDemoSeeded}
          />

          {/* Filters */}
          <FilterSection title="Status">
            {['Running', 'Completed', 'Failed', 'Paused'].map((s) => (
              <CustomCheckbox
                key={s}
                label={s}
                checked={!!statusFilters[s]}
                onChange={() => toggle(setStatusFilters, s)}
              />
            ))}
          </FilterSection>

          <FilterSection title="Document Type">
            {['Loan Agreement', 'Disclosure', 'Policy Manual', 'Amendment'].map((t) => (
              <CustomCheckbox
                key={t}
                label={t}
                checked={!!docTypeFilters[t]}
                onChange={() => toggle(setDocTypeFilters, t)}
              />
            ))}
          </FilterSection>

          <FilterSection title="Playbook">
            {['Microfinance v1', 'Consumer Lending', 'Regulatory Check'].map((p) => (
              <CustomCheckbox
                key={p}
                label={p}
                checked={!!playbookFilters[p]}
                onChange={() => toggle(setPlaybookFilters, p)}
              />
            ))}
          </FilterSection>

          {/* Recent Runs */}
          <div>
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/45 block mb-2.5">
              Recent Runs
            </span>
            <div className="space-y-2">
              {runs.length === 0 && (
                <p className="text-[12px] text-white/30 italic">No runs yet</p>
              )}
              {runs.map((run) => {
                const isActive = run.id === activeRunId;
                const label = run.pile_name
                  ? `${run.id.slice(0, 8)} — ${run.pile_name}`
                  : run.filename
                    ? `${run.id.slice(0, 8)} — ${run.filename}`
                    : `Run ${run.id.slice(0, 8)}`;
                return (
                  <div
                    key={run.id}
                    onClick={() => onRunSelect(run)}
                    className={`
                      group rounded-lg border px-3 py-2.5 cursor-pointer transition-all duration-150
                      ${isActive
                        ? 'border-indigo-500/40 bg-indigo-500/[0.08] border-l-[3px] border-l-indigo-500'
                        : 'border-white/[0.06] bg-white/[0.02] hover:border-white/[0.14] hover:bg-white/[0.04]'
                      }
                    `}
                  >
                    <div className="flex items-center gap-2.5">
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT_COLOR[run.status] ?? 'bg-white/30'} ${run.status === 'running' ? 'animate-pulse' : ''}`} />
                      <div className="min-w-0 flex-1">
                        <span className={`text-[13px] font-medium truncate block ${isActive ? 'text-white/90' : 'text-white/55 group-hover:text-white/75'}`}>
                          {label}
                        </span>
                        {run.pile_name && (
                          <span className="text-[10px] text-white/30 truncate block">
                            Pile: {run.pile_name}
                          </span>
                        )}
                      </div>
                      {(run.needs_recheck_count ?? 0) > 0 && (
                        <span
                          className="flex-shrink-0 inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider bg-amber-500/15 text-amber-300 border border-amber-500/30"
                          title="Has approvals made with zero/null citations — flagged for re-review"
                        >
                          {run.needs_recheck_count} recheck
                        </span>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); onRunDelete(run.id); }}
                        className="opacity-0 group-hover:opacity-100 p-1 rounded text-white/30 hover:text-rose-400 hover:bg-rose-500/10 transition-all"
                        title="Delete run"
                      >
                        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                          <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── TopBar ──────────────────────────────────────────────────────────────────

type OverlayMode = 'none' | 'history' | 'cost' | 'review' | 'deliverable' | 'findings';

function TopBar({ runStatus, connectionLost, overlayMode, onOverlayChange, totalCost, onStartPipeline, isUploading, activeRunId, activeFilename, canResume, isResuming, onResume, pendingCount, onOpenReview, onViewReport }: {
  runStatus: string;
  connectionLost: boolean;
  overlayMode: OverlayMode;
  onOverlayChange: (mode: OverlayMode) => void;
  totalCost: string | null;
  onStartPipeline: () => void;
  isUploading: boolean;
  activeRunId: string | null;
  activeFilename: string | null;
  canResume: boolean;
  isResuming: boolean;
  onResume: () => void;
  pendingCount: number;
  onOpenReview: () => void;
  onViewReport: () => void;
}) {
  return (
    <div className="flex items-center justify-between h-12 px-4 border-b border-white/[0.06] bg-[#0c0f1a]/80 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-white/90">
          {activeRunId ? `Run ${activeRunId.slice(0, 8)}` : 'No active run'}
        </span>
        {activeFilename && (
          <>
            <span className="text-white/20">·</span>
            <span className="text-sm text-white/40 truncate max-w-[200px]">{activeFilename}</span>
          </>
        )}
        {connectionLost && (
          <span className="flex items-center gap-1 rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-medium text-amber-300 border border-amber-500/30">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
            Reconnecting...
          </span>
        )}
        {!connectionLost && runStatus && (
          <span className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium border ${
            runStatus === 'running' ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30' :
            runStatus === 'completed' ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' :
            runStatus === 'failed' ? 'bg-rose-500/20 text-rose-300 border-rose-500/30' :
            'bg-amber-500/20 text-amber-300 border-amber-500/30'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${
              runStatus === 'running' ? 'bg-indigo-400 animate-pulse' :
              runStatus === 'completed' ? 'bg-emerald-400' :
              runStatus === 'failed' ? 'bg-rose-400' : 'bg-amber-400'
            }`} />
            {runStatus}
          </span>
        )}
        {/* Cost mode total */}
        {overlayMode === 'cost' && totalCost && (
          <span className="flex items-center gap-1 rounded-full bg-violet-500/15 px-2.5 py-0.5 text-[10px] font-mono text-violet-300 border border-violet-500/25">
            Σ {totalCost}
          </span>
        )}
        {/* Pending approvals badge — always visible in the header so a run
            waiting on a human can't be missed. Clicking opens the Review tab. */}
        {pendingCount > 0 && (
          <button
            onClick={onOpenReview}
            className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium border transition-colors ${
              overlayMode === 'review'
                ? 'bg-amber-500/25 text-amber-200 border-amber-500/40'
                : 'bg-amber-500/15 text-amber-300 border-amber-500/30 hover:bg-amber-500/25 animate-pulse'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-amber-400" />
            {pendingCount} pending review
          </button>
        )}
      </div>

      <div className="flex items-center gap-2">
        {/* Overlay mode toggle */}
        <div className="flex rounded-md border border-white/[0.08] overflow-hidden">
          {(['none', 'history', 'cost', 'review', 'deliverable', 'findings'] as OverlayMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => onOverlayChange(mode)}
              className={`relative px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider transition-colors ${
                overlayMode === mode
                  ? 'bg-indigo-500/20 text-indigo-300'
                  : 'text-white/40 hover:text-white/60 hover:bg-white/[0.03]'
              }`}
            >
              {mode === 'none' ? 'Status' : mode}
              {mode === 'review' && pendingCount > 0 && overlayMode !== 'review' && (
                <span className="absolute -top-1 -right-1 flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-amber-500 text-[9px] font-bold text-black shadow-sm">
                  {pendingCount > 99 ? '99+' : pendingCount}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* View Report button — only for completed/failed runs */}
        {(runStatus === 'completed' || runStatus === 'failed') && activeRunId && (
          <button
            onClick={onViewReport}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-white/80 border border-white/[0.12] hover:bg-white/[0.05] hover:text-white transition-colors"
          >
            Report
          </button>
        )}

        <button
          onClick={onStartPipeline}
          disabled={isUploading || runStatus === 'running'}
          className={`rounded-md px-4 py-1.5 text-sm font-medium text-white transition-colors shadow-sm ${
            isUploading || runStatus === 'running'
              ? 'bg-indigo-600/50 cursor-not-allowed'
              : 'bg-indigo-600 hover:bg-indigo-500 shadow-indigo-600/20'
          }`}
        >
          {isUploading ? 'Uploading...' : runStatus === 'running' ? 'Running...' : 'Start pipeline'}
        </button>

        <ResumeButton canResume={canResume} isResuming={isResuming} onResume={onResume} />
      </div>
    </div>
  );
}

// ─── Node/Edge builders ──────────────────────────────────────────────────────

/**
 * Build the pipeline graph with proper DAG structure.
 * Parallel branches (match_rules / match_rules_against_sources) are expressed
 * via edges, and dagre lays them out side-by-side automatically.
 *
 * Graph topology:
 *   start → ingest → extract_text → classify_document → chunk → embed → extract_claims
 *     extract_claims → match_rules
 *     extract_claims → match_rules_against_sources
 *   match_rules → merge_findings
 *   match_rules_against_sources → merge_findings
 *   merge_findings → score_confidence → route_to_queue → human_review → finalize
 */

interface NodeDef {
  id: string;
  label: string;
  icon: string;
  type: 'stageNode' | 'mergeNode' | 'addNode';
}

const GRAPH_NODES: NodeDef[] = [
  { id: 'start', label: 'Start', icon: 'play', type: 'stageNode' },
  { id: 'ingest', label: 'Ingest', icon: 'download', type: 'stageNode' },
  { id: 'extract_text', label: 'Extract Text', icon: 'document', type: 'stageNode' },
  { id: 'classify_document', label: 'Classify', icon: 'brain', type: 'stageNode' },
  { id: 'chunk', label: 'Chunk', icon: 'document', type: 'stageNode' },
  { id: 'embed', label: 'Embed', icon: 'document', type: 'stageNode' },
  { id: 'extract_claims', label: 'Extract Claims', icon: 'search', type: 'stageNode' },
  // Parallel branch
  { id: 'match_rules', label: 'Match Rules', icon: 'search', type: 'stageNode' },
  { id: 'match_rules_against_sources', label: 'Match Sources', icon: 'search', type: 'stageNode' },
  // Convergence
  { id: 'merge_findings', label: 'Merge Findings', icon: 'merge', type: 'mergeNode' },
  { id: 'score_confidence', label: 'Score', icon: 'brain', type: 'stageNode' },
  { id: 'route_to_queue', label: 'Route to Queue', icon: 'shield', type: 'stageNode' },
  { id: 'human_review', label: 'Human Review', icon: 'shield', type: 'stageNode' },
  { id: 'finalize', label: 'Finalize', icon: 'play', type: 'stageNode' },
];

/** Edges defining the DAG structure (source → target) */
const GRAPH_EDGES: Array<[string, string]> = [
  ['start', 'ingest'],
  ['ingest', 'extract_text'],
  ['extract_text', 'classify_document'],
  ['classify_document', 'chunk'],
  ['chunk', 'embed'],
  ['embed', 'extract_claims'],
  // Parallel fan-out from extract_claims
  ['extract_claims', 'match_rules'],
  ['extract_claims', 'match_rules_against_sources'],
  // Converge into merge
  ['match_rules', 'merge_findings'],
  ['match_rules_against_sources', 'merge_findings'],
  // Continue linear
  ['merge_findings', 'score_confidence'],
  ['score_confidence', 'route_to_queue'],
  ['route_to_queue', 'human_review'],
  ['human_review', 'finalize'],
];

function buildNodes(nodeStatuses: Record<string, NodeStatus>): Node[] {
  return GRAPH_NODES.map((def) => {
    const status: NodeStatus =
      def.id === 'start'
        ? (nodeStatuses['ingest'] === 'complete' || nodeStatuses['ingest'] === 'processing')
          ? 'complete'
          : 'ready'
        : (nodeStatuses[def.id] ?? 'ready');

    return {
      id: def.id,
      type: def.type,
      // Position will be overwritten by dagre layout — placeholder
      position: { x: 0, y: 0 },
      data: { label: def.label, status, icon: def.icon },
      draggable: true,
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    };
  });
}

function buildEdges(
  nodeStatuses: Record<string, NodeStatus>,
  edgeDecisions: Record<string, EdgeDecision>
): Edge[] {
  const edges: Edge[] = GRAPH_EDGES.map(([src, tgt]) => {
    const edgeId = `e-${src}-${tgt}`;
    const decision = edgeDecisions[edgeId] ?? undefined;
    return {
      id: edgeId,
      source: src,
      target: tgt,
      type: 'smoothEdge',
      data: { sourceStatus: nodeStatuses[src] ?? 'ready', decision },
    };
  });

  // Add escalation edges (visual — from failed/escalated nodes to route_to_queue)
  for (const [nodeName, status] of Object.entries(nodeStatuses)) {
    if (status === 'escalated' && nodeName !== 'route_to_queue') {
      edges.push({
        id: `e-escalate-${nodeName}-rtq`,
        source: nodeName,
        target: 'route_to_queue',
        type: 'smoothEdge',
        data: { sourceStatus: 'escalated', decision: 'escalate' as EdgeDecision },
      });
    }
  }

  return edges;
}

// ─── Mock overlay data ───────────────────────────────────────────────────────

// ─── Main Component ──────────────────────────────────────────────────────────

export function PipelineCanvas() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeLabel, setSelectedNodeLabel] = useState('');
  const [overlayMode, setOverlayMode] = useState<OverlayMode>('none');

  // Upload and run state
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeFilename, setActiveFilename] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [_runs, setRuns] = useState<RunListItem[]>([]);
  const [showReport, setShowReport] = useState(false);

  // Pile state
  const [selectedPileId, setSelectedPileId] = useState<string | null>(null);
  const [selectedPileName, setSelectedPileName] = useState<string | null>(null);

  // Poll real state via SSE/polling
  const { nodeStatuses, edgeDecisions, recentTransitions, runState, connectionLost } = usePipelineState(activeRunId);

  // Cost overlay data (fetched from backend)
  const [costData, setCostData] = useState<Record<string, { time: string; cost: string }>>({});
  const [totalCostLabel, setTotalCostLabel] = useState<string | null>(null);

  // History overlay data (fetched from backend)
  const [historyCounts, setHistoryCounts] = useState<Record<string, number>>({});

  // Resume state
  const [isResuming, setIsResuming] = useState(false);

  // Pending approvals count (fetched from backend for current run)
  const [pendingApprovalsCount, setPendingApprovalsCount] = useState(0);

  // Fetch cost data when overlay switches to 'cost' or activeRunId changes
  useEffect(() => {
    if (overlayMode !== 'cost' || !activeRunId) {
      return;
    }
    fetchRunCost(activeRunId)
      .then((result) => {
        const perNode: Record<string, { time: string; cost: string }> = {};
        for (const stage of result.stages) {
          const timeSec = stage.duration_ms != null ? `${(stage.duration_ms / 1000).toFixed(1)}s` : '—';
          const costUsd = stage.cost_usd != null ? `$${stage.cost_usd.toFixed(2)}` : '—';
          perNode[stage.stage] = { time: timeSec, cost: costUsd };
        }
        setCostData(perNode);
        const totalSec = (result.total_duration_ms / 1000).toFixed(1);
        setTotalCostLabel(`$${result.total_cost_usd.toFixed(2)} · ${totalSec}s`);
      })
      .catch(() => {
        setCostData({});
        setTotalCostLabel(null);
      });
  }, [overlayMode, activeRunId]);

  // Fetch history data when overlay switches to 'history' or activeRunId changes
  useEffect(() => {
    if (overlayMode !== 'history' || !activeRunId) {
      return;
    }
    fetchRunHistory(activeRunId)
      .then((result) => {
        // Count events per node by grouping on entity_id (node name) or action
        const counts: Record<string, number> = {};
        for (const entry of result.entries) {
          // entity_id often contains the node/stage name
          const key = entry.entity_id;
          counts[key] = (counts[key] ?? 0) + 1;
        }
        setHistoryCounts(counts);
      })
      .catch(() => {
        setHistoryCounts({});
      });
  }, [overlayMode, activeRunId]);

  // Live poll of pending approvals count while a run is active.
  // Runs every ~10s so a run waiting on a human is always reflected in
  // the header badge, even mid-run (items appear as route_to_queue fires).
  useEffect(() => {
    if (!activeRunId) {
      setPendingApprovalsCount(0);
      return;
    }

    let cancelled = false;

    const fetchPending = () => {
      fetch(`${import.meta.env.VITE_API_BASE_URL ?? ''}/approval/runs/${activeRunId}/queue`)
        .then((res) => res.ok ? res.json() : null)
        .then((data) => {
          if (!cancelled && data) setPendingApprovalsCount(data.pending ?? 0);
        })
        .catch(() => {});
    };

    fetchPending();
    const interval = setInterval(fetchPending, 10_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [activeRunId]);

  // Close report when active run changes (report is per-run; user must re-open explicitly)
  useEffect(() => {
    setShowReport(false);
  }, [activeRunId]);

  // Close the node detail panel when an overlay tab opens —
  // they share the same right-edge overlay space.
  useEffect(() => {
    if (overlayMode !== 'none' && overlayMode !== 'history' && overlayMode !== 'cost') {
      setSelectedNodeId(null);
    }
  }, [overlayMode]);

  // Load existing runs on mount
  useEffect(() => {
    fetchPipelineRuns().then((fetchedRuns) => {
      setRuns(fetchedRuns);
      // Auto-select the latest running or most recent run
      const running = fetchedRuns.find((r) => r.status === 'running');
      if (running) {
        setActiveRunId(running.id);
        setActiveFilename(running.filename);
      } else if (fetchedRuns.length > 0) {
        setActiveRunId(fetchedRuns[0].id);
        setActiveFilename(fetchedRuns[0].filename);
      }
    }).catch(() => {});
  }, []);

  // Handle "Start pipeline" click — requires a selected pile with documents
  const handleStartPipeline = useCallback(async () => {
    if (!selectedPileId) {
      alert('Please select a pile first.');
      return;
    }

    setIsUploading(true);
    try {
      // Fetch pile detail to get first document for pipeline execution
      const detail = await fetchPileDetail(selectedPileId);
      if (detail.documents.length === 0) {
        alert('The selected pile has no documents. Upload files first.');
        setIsUploading(false);
        return;
      }

      const firstDoc = detail.documents[0];

      // Start pipeline — only pass pile_id; backend resolves documents + versions
      const startResult = await startPipelineWithPile(selectedPileId);

      // Switch to tracking this run
      setActiveRunId(startResult.run_id);
      setActiveFilename(selectedPileName ?? detail.name);

      // Add to local runs
      setRuns((prev) => [{
        id: startResult.run_id,
        status: 'running',
        started_at: new Date().toISOString(),
        document_id: firstDoc.document_id,
        filename: firstDoc.filename,
        pile_id: selectedPileId,
        pile_name: selectedPileName ?? detail.name,
      }, ...prev]);

    } catch (err) {
      console.error('Pipeline start failed:', err);
      alert(`Failed to start pipeline: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setIsUploading(false);
    }
  }, [selectedPileId, selectedPileName]);

  // Handle resume for paused/interrupted/cancelled runs
  const handleResume = useCallback(async () => {
    if (!activeRunId) return;
    setIsResuming(true);
    try {
      await resumeRun(activeRunId);
      // Re-fetch runs to update status in sidebar
      fetchPipelineRuns().then(setRuns).catch(() => {});
    } catch (err) {
      console.error('Resume failed:', err);
      alert(`Failed to resume: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setIsResuming(false);
    }
  }, [activeRunId]);

  // Determine if the current run is resumable
  const canResume = Boolean(
    activeRunId &&
    runState &&
    ['paused', 'cancelled', 'failed'].includes(runState.run_status)
  );

  // Handle pile selection
  const handlePileSelect = useCallback((pile: PileListItem) => {
    setSelectedPileId(pile.id);
    setSelectedPileName(pile.name);
  }, []);

  const handleDemoSeeded = useCallback(async (result: SeedDemoResponse) => {
    if (!result.pile_id) return;

    const detail = await fetchPileDetail(result.pile_id);
    setSelectedPileId(result.pile_id);
    setSelectedPileName(detail.name);

    if (detail.documents.length === 0) return;

    setIsUploading(true);
    try {
      const startResult = await startPipelineWithPile(result.pile_id);
      const firstDoc = detail.documents[0];
      setActiveRunId(startResult.run_id);
      setActiveFilename(detail.name);
      setRuns((prev) => [{
        id: startResult.run_id,
        status: 'running',
        started_at: new Date().toISOString(),
        document_id: firstDoc.document_id,
        filename: firstDoc.filename,
        pile_id: result.pile_id ?? null,
        pile_name: detail.name,
      }, ...prev]);
    } catch (err) {
      console.error('Demo pipeline start failed:', err);
      alert(`Demo seeded, but failed to start the run: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setIsUploading(false);
    }
  }, []);

  // Callback when documents are uploaded to a pile (refresh runs, etc.)
  const handleDocumentsUploaded = useCallback(() => {
    // No-op for now; PilesPanel handles its own refresh
  }, []);

  const nodeTypes = useMemo(() => ({
    stageNode: PipelineNode,
    mergeNode: MergeNode,
    addNode: AddNode,
  }), []);

  const edgeTypes = useMemo(() => ({
    smoothEdge: SmoothEdge,
  }), []);

  // Track which nodes just transitioned for animation
  const transitionedNodeIds = useMemo(
    () => new Set(recentTransitions.map((t) => t.nodeId)),
    [recentTransitions]
  );

  // Build edges from graph structure (pure derivation)
  const edges = useMemo(() => buildEdges(nodeStatuses, edgeDecisions), [nodeStatuses, edgeDecisions]);

  // --- Node state management ---
  // We maintain nodes in useState so drag changes persist.
  // On mount (and when topology changes), we compute layout positions.
  // On data-only changes (status, overlay), we update data without resetting positions.

  const [nodes, setNodes] = useState<Node[]>(() => {
    const raw = buildNodes(nodeStatuses);
    const laid = applyDagreLayout(raw, edges, { nodesep: 100, ranksep: 120 });
    return laid.map((node) => ({
      ...node,
      data: {
        ...node.data,
        overlayMode,
        historyCount: historyCounts[node.id] ?? 0,
        costData: costData[node.id] ?? null,
      },
    }));
  });

  // Update node data when pipeline status or overlay mode changes.
  // Preserves user-dragged positions by only updating `data`, not `position`.
  //
  // STATUS → COLOUR CONTRACT:
  //   The `status` field in each node's data drives the visual appearance via
  //   STATUS_CONFIG in pipelineColors.ts. Values come from usePipelineState which
  //   derives them from the backend /runs/{id}/state response:
  //     'ready'      → neutral/grey (node hasn't run yet)
  //     'processing' → indigo/blue with pulse (node is executing now)
  //     'complete'   → emerald/green (node finished successfully)
  //     'skipped'    → amber/muted (node was skipped)
  //     'escalated'  → amber/bright (node escalated to human review)
  //     'failed'     → rose/red (node errored permanently)
  //     'retrying'   → indigo with pulse (node is retrying after transient error)
  //
  //   This effect MUST run whenever nodeStatuses changes so nodes re-render with
  //   the correct colour. Do NOT add early-return guards here.
  useEffect(() => {
    setNodes((currentNodes) =>
      currentNodes.map((node) => {
        const status: NodeStatus =
          node.id === 'start'
            ? (nodeStatuses['ingest'] === 'complete' || nodeStatuses['ingest'] === 'processing')
              ? 'complete'
              : 'ready'
            : (nodeStatuses[node.id] ?? 'ready');

        const nodeDef = GRAPH_NODES.find((n) => n.id === node.id);
        return {
          ...node,
          data: {
            label: nodeDef?.label ?? node.id,
            status,
            icon: nodeDef?.icon ?? 'document',
            justTransitioned: transitionedNodeIds.has(node.id),
            overlayMode,
            historyCount: historyCounts[node.id] ?? 0,
            costData: costData[node.id] ?? null,
          },
        };
      })
    );
  }, [nodeStatuses, transitionedNodeIds, overlayMode, costData, historyCounts]);

  // Handle node changes (drag, selection, etc.) — this is what makes
  // dragging work in React Flow's controlled mode.
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((nds) => applyNodeChanges(changes, nds));
  }, []);

  const handleNodeClick = useCallback((_: unknown, node: Node) => {
    if (node.id === 'start') return;
    setSelectedNodeId(node.id);
    setSelectedNodeLabel((node.data as { label?: string }).label ?? node.id);
  }, []);

  const handleClosePanel = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  return (
    <div className="flex h-screen w-screen bg-[#0b0f19] text-white overflow-hidden">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        runs={_runs}
        activeRunId={activeRunId}
        onRunSelect={(run) => {
          setActiveRunId(run.id);
          setActiveFilename(run.filename);
        }}
        onRunDelete={async (runId) => {
          if (!confirm('Delete this run? This cannot be undone.')) return;
          try {
            await deleteRun(runId);
            setRuns((prev) => prev.filter((r) => r.id !== runId));
            if (activeRunId === runId) {
              setActiveRunId(null);
              setActiveFilename(null);
            }
          } catch (err) {
            alert(`Failed to delete: ${err instanceof Error ? err.message : 'Unknown error'}`);
          }
        }}
        selectedPileId={selectedPileId}
        onPileSelect={handlePileSelect}
        onDocumentsUploaded={handleDocumentsUploaded}
        onDemoSeeded={handleDemoSeeded}
      />

      <div className="flex-1 flex flex-col min-w-0">
        <TopBar
          runStatus={runState?.run_status ?? ''}
          connectionLost={connectionLost}
          overlayMode={overlayMode}
          onOverlayChange={setOverlayMode}
          totalCost={overlayMode === 'cost' ? totalCostLabel : null}
          onStartPipeline={handleStartPipeline}
          isUploading={isUploading}
          activeRunId={activeRunId}
          activeFilename={activeFilename}
          canResume={canResume}
          isResuming={isResuming}
          onResume={handleResume}
          pendingCount={pendingApprovalsCount}
          onOpenReview={() => setOverlayMode('review')}
          onViewReport={() => setShowReport(true)}
        />

        {/* Pile indicator in top bar */}
        {selectedPileName && (
          <div className="px-4 py-1.5 border-b border-white/[0.06] text-[12px] text-white/50 flex items-center gap-2">
            <svg className="w-3.5 h-3.5 text-indigo-400/70" viewBox="0 0 16 16" fill="currentColor">
              <path d="M1 3.5A1.5 1.5 0 012.5 2h3.879a1.5 1.5 0 011.06.44l1.122 1.12A1.5 1.5 0 009.621 4H13.5A1.5 1.5 0 0115 5.5v7a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 011 12.5v-9z" />
            </svg>
            <span>Pile: <span className="text-white/70 font-medium">{selectedPileName}</span></span>
          </div>
        )}

        <div className="flex-1 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={onNodesChange}
            onNodeClick={handleNodeClick}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            proOptions={{ hideAttribution: true }}
            className="!bg-transparent"
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={20}
              size={1}
              color="rgba(255,255,255,0.04)"
            />
            <Controls
              className="!bg-[#141927] !border-white/[0.08] !rounded-lg !shadow-xl [&>button]:!bg-transparent [&>button]:!text-white/50 [&>button]:!border-white/[0.06] [&>button:hover]:!bg-white/[0.05] [&>button:hover]:!text-white/80"
              position="bottom-right"
            />
          </ReactFlow>

          {/* Detail panel overlay — NOT inside ReactFlow so it persists across mode changes */}
          <NodeDetailPanel
            nodeId={selectedNodeId}
            nodeLabel={selectedNodeLabel}
            onClose={handleClosePanel}
            runId={activeRunId}
          />

          {/* Pending Review overlay — every queue item for this run */}
          <PendingReviewPanel
            runId={activeRunId}
            open={overlayMode === 'review'}
            onClose={() => setOverlayMode('none')}
            onPendingCountChange={setPendingApprovalsCount}
          />

          {/* Deliverable Register overlay — assembled output + update diff */}
          <DeliverablePanel
            runId={activeRunId}
            open={overlayMode === 'deliverable'}
            onClose={() => setOverlayMode('none')}
          />

          {/* Findings audit-trail overlay — every finding, resolved or not */}
          <FindingsPanel
            runId={activeRunId}
            open={overlayMode === 'findings'}
            onClose={() => setOverlayMode('none')}
          />
        </div>
      </div>

      {/* Report panel — opened explicitly via Report button */}
      <ReportPanel
        runId={activeRunId}
        runStatus={runState?.run_status ?? null}
        onClose={() => setShowReport(false)}
        open={showReport}
        onOpenApprovals={() => setOverlayMode('review')}
      />
    </div>
  );
}

export default PipelineCanvas;
