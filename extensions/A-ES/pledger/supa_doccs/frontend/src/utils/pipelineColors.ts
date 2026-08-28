import type { NodeStatus } from '@/types/pipeline';

/**
 * STATUS → COLOUR CONTRACT
 *
 * This mapping is the single source of truth for node visual appearance.
 * The backend /runs/{id}/state endpoint returns per-node data; the frontend
 * hook (usePipelineState.ts) derives a NodeStatus for each node; this config
 * turns that status into Tailwind classes applied by PipelineNode / MergeNode.
 *
 * Backend status values that drive derivation (in usePipelineState.ts):
 *   completed_nodes[]  → 'complete'   (green)
 *   current_node + running → 'processing' (indigo pulse)
 *   current_node + error + retries > 0 → 'retrying' (indigo pulse)
 *   current_node + error (permanent) → 'failed' (rose/red)
 *   skipped_nodes[]    → 'skipped'    (amber muted)
 *   retries[node] >= 3 → 'escalated'  (amber bright)
 *   otherwise          → 'ready'      (neutral grey)
 *
 * DO NOT rename these keys without updating PipelineNode.tsx, MergeNode.tsx,
 * usePipelineState.ts, and the backend state endpoint contract.
 */
export const STATUS_CONFIG: Record<NodeStatus, { border: string; glow: string; text: string; label: string; dot: string }> = {
  ready: {
    border: 'border-white/20',
    glow: '',
    text: 'text-white/40',
    label: 'Ready to process',
    dot: 'bg-white/30',
  },
  processing: {
    border: 'border-indigo-500',
    glow: 'shadow-lg shadow-indigo-500/20',
    text: 'text-indigo-300',
    label: 'Processing...',
    dot: 'bg-indigo-400 animate-pulse',
  },
  complete: {
    border: 'border-emerald-500',
    glow: 'shadow-md shadow-emerald-500/15',
    text: 'text-emerald-300',
    label: 'Complete',
    dot: 'bg-emerald-400',
  },
  skipped: {
    border: 'border-amber-400/60',
    glow: '',
    text: 'text-amber-300/70',
    label: 'Skipped',
    dot: 'bg-amber-400/60',
  },
  escalated: {
    border: 'border-amber-500',
    glow: 'shadow-md shadow-amber-500/15',
    text: 'text-amber-300',
    label: 'Escalated',
    dot: 'bg-amber-400',
  },
  failed: {
    border: 'border-rose-500',
    glow: 'shadow-md shadow-rose-500/15',
    text: 'text-rose-300',
    label: 'Failed',
    dot: 'bg-rose-400',
  },
  retrying: {
    border: 'border-indigo-400',
    glow: 'shadow-md shadow-indigo-400/15',
    text: 'text-indigo-300',
    label: 'Retrying...',
    dot: 'bg-indigo-400 animate-pulse',
  },
};
