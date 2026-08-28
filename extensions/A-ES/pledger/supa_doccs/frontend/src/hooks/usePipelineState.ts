/**
 * Hook to track pipeline run state via SSE (real-time) with polling fallback.
 * Drives the canvas directly from backend state.
 *
 * KEY DESIGN: Uses Server-Sent Events when a run is active for instant updates.
 * Falls back to polling /runs/{run_id}/state every 2s when SSE is unavailable.
 * State diffing — only signals transitions when node statuses actually change.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import type { NodeStatus, EdgeDecision, PipelineRunState } from '@/types/pipeline';
import { PIPELINE_NODES } from '@/types/pipeline';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';
const POLL_INTERVAL = 2000;

export interface NodeTransition {
  nodeId: string;
  from: NodeStatus;
  to: NodeStatus;
  timestamp: number;
}

export interface DerivedPipelineView {
  nodeStatuses: Record<string, NodeStatus>;
  edgeDecisions: Record<string, EdgeDecision>;
  /** Nodes whose status changed on the most recent update (empty if no change) */
  recentTransitions: NodeTransition[];
  runState: PipelineRunState | null;
  isPolling: boolean;
  error: Error | null;
  connectionLost: boolean;
}

function deriveNodeStatus(
  nodeName: string,
  state: PipelineRunState
): NodeStatus {
  // STATUS DERIVATION — maps backend state to visual status.
  // Priority order matters: completed > skipped > current/running > escalated > ready.
  // See pipelineColors.ts for the full status→colour contract.
  if (state.completed_nodes.includes(nodeName)) return 'complete';
  if (state.skipped_nodes.some((s) => s.node_name === nodeName)) return 'skipped';

  if (state.current_node === nodeName) {
    if (state.node_status === 'error') {
      const retryCount = state.retries[nodeName] ?? 0;
      if (retryCount > 0 && state.error_type === 'transient') return 'retrying';
      return 'failed';
    }
    return 'processing';
  }

  if (state.retries[nodeName] && state.retries[nodeName] >= 3) return 'escalated';
  return 'ready';
}

function deriveEdgeDecisions(state: PipelineRunState): Record<string, EdgeDecision> {
  const decisions: Record<string, EdgeDecision> = {};

  for (const [nodeName, count] of Object.entries(state.retries)) {
    if (count > 0) {
      decisions[`retry-${nodeName}`] = 'retry';
    }
  }

  for (const skipped of state.skipped_nodes) {
    const nodeIdx = PIPELINE_NODES.indexOf(skipped.node_name as typeof PIPELINE_NODES[number]);
    if (nodeIdx > 0) {
      const prevNode = PIPELINE_NODES[nodeIdx - 1];
      decisions[`e-${prevNode}-${skipped.node_name}`] = 'skip';
    }
  }

  if (state.node_status === 'error' && state.current_node !== 'route_to_queue') {
    decisions[`e-${state.current_node}-route_to_queue`] = 'escalate';
  }

  return decisions;
}

async function fetchRunState(runId: string): Promise<PipelineRunState> {
  const response = await fetch(`${BASE_URL}/runs/${runId}/state`);
  if (!response.ok) throw new Error(`Failed to fetch run state: ${response.status}`);
  return response.json();
}

/**
 * Apply an SSE event to derive a PipelineRunState update.
 */
function applySSEEvent(event: any, current: PipelineRunState | null): PipelineRunState | null {
  if (!event) return current;

  const type = event.type;

  if (type === 'node_start') {
    // A node is starting — mark it as processing
    return {
      run_id: event.run_id ?? current?.run_id ?? '',
      current_node: event.node,
      node_status: 'running',
      completed_nodes: current?.completed_nodes ?? [],
      skipped_nodes: current?.skipped_nodes ?? [],
      retries: current?.retries ?? {},
      error_type: null,
      error_detail: null,
      run_status: 'running',
    };
  }

  if (type === 'node_complete') {
    return {
      run_id: event.run_id ?? current?.run_id ?? '',
      current_node: event.current_node ?? event.node,
      node_status: event.status ?? 'completed',
      completed_nodes: event.completed_nodes ?? current?.completed_nodes ?? [],
      skipped_nodes: current?.skipped_nodes ?? [],
      retries: current?.retries ?? {},
      error_type: event.error_detail ? 'transient' : null,
      error_detail: event.error_detail ?? null,
      run_status: event.run_status ?? 'running',
    };
  }

  if (type === 'run_complete') {
    return {
      run_id: event.run_id ?? current?.run_id ?? '',
      current_node: current?.current_node ?? 'finalize',
      node_status: 'completed',
      completed_nodes: event.completed_nodes ?? current?.completed_nodes ?? [],
      skipped_nodes: current?.skipped_nodes ?? [],
      retries: current?.retries ?? {},
      error_type: event.error ? 'permanent' : null,
      error_detail: event.error ?? null,
      run_status: event.status ?? 'completed',
    };
  }

  return current;
}

export function usePipelineState(runId: string | null): DerivedPipelineView {
  const [runState, setRunState] = useState<PipelineRunState | null>(null);
  const [recentTransitions, setRecentTransitions] = useState<NodeTransition[]>([]);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [connectionLost, setConnectionLost] = useState(false);
  const mountedRef = useRef(true);
  const prevStatusesRef = useRef<Record<string, NodeStatus>>({});
  const eventSourceRef = useRef<EventSource | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Diff and emit transitions
  const emitTransitions = useCallback((newState: PipelineRunState) => {
    const newStatuses: Record<string, NodeStatus> = {};
    for (const node of PIPELINE_NODES) {
      newStatuses[node] = deriveNodeStatus(node, newState);
    }

    const transitions: NodeTransition[] = [];
    const prevStatuses = prevStatusesRef.current;
    for (const node of PIPELINE_NODES) {
      const prev = prevStatuses[node];
      const next = newStatuses[node];
      if (prev !== undefined && prev !== next) {
        transitions.push({ nodeId: node, from: prev, to: next, timestamp: Date.now() });
      }
    }

    prevStatusesRef.current = newStatuses;

    if (transitions.length > 0) {
      setRecentTransitions(transitions);
      setTimeout(() => {
        if (mountedRef.current) setRecentTransitions([]);
      }, 600);
    }
  }, []);

  // Try SSE connection
  useEffect(() => {
    mountedRef.current = true;
    if (!runId) return;

    let sseConnected = false;

    // Attempt SSE connection
    const sseUrl = `${BASE_URL}/runs/${runId}/stream`;
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    es.addEventListener('connected', (_e: MessageEvent) => {
      sseConnected = true;
      setConnectionLost(false);
      setError(null);
      // Stop polling if SSE connected
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    });

    es.addEventListener('node_start', (e: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const data = JSON.parse(e.data);
        setRunState((prev) => {
          const updated = applySSEEvent(data, prev);
          if (updated) emitTransitions(updated);
          return updated;
        });
      } catch {}
    });

    es.addEventListener('node_complete', (e: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const data = JSON.parse(e.data);
        setRunState((prev) => {
          const updated = applySSEEvent(data, prev);
          if (updated) emitTransitions(updated);
          return updated;
        });
      } catch {}
    });

    es.addEventListener('run_complete', (e: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const data = JSON.parse(e.data);
        setRunState((prev) => {
          const updated = applySSEEvent(data, prev);
          if (updated) emitTransitions(updated);
          return updated;
        });
      } catch {}
      // Close SSE on completion
      es.close();
    });

    es.onerror = () => {
      if (!mountedRef.current) return;
      // SSE failed — fall back to polling
      sseConnected = false;
      es.close();
      startPolling();
    };

    // Also do an initial fetch to get current state
    fetchRunState(runId)
      .then((state) => {
        if (!mountedRef.current) return;
        setRunState(state);
        emitTransitions(state);
        setConnectionLost(false);
        setError(null);
      })
      .catch((err) => {
        if (!mountedRef.current) return;
        setError(err instanceof Error ? err : new Error('Unknown'));
      });

    // Polling fallback
    function startPolling() {
      if (pollIntervalRef.current) return;
      pollIntervalRef.current = setInterval(async () => {
        if (!mountedRef.current || !runId) return;
        setIsPolling(true);
        try {
          const state = await fetchRunState(runId);
          if (!mountedRef.current) return;
          setRunState(state);
          emitTransitions(state);
          setConnectionLost(false);
          setError(null);

          // Stop polling if run is complete
          if (state.run_status === 'completed' || state.run_status === 'failed') {
            if (pollIntervalRef.current) {
              clearInterval(pollIntervalRef.current);
              pollIntervalRef.current = null;
            }
          }
        } catch (err) {
          if (!mountedRef.current) return;
          setError(err instanceof Error ? err : new Error('Unknown'));
          setConnectionLost(true);
        } finally {
          if (mountedRef.current) setIsPolling(false);
        }
      }, POLL_INTERVAL);
    }

    // Start polling as backup (SSE will disable it if it connects)
    const pollingTimeout = setTimeout(() => {
      if (!sseConnected && mountedRef.current) {
        startPolling();
      }
    }, 1000);

    return () => {
      mountedRef.current = false;
      es.close();
      eventSourceRef.current = null;
      clearTimeout(pollingTimeout);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [runId, emitTransitions]);

  // Derive current view
  const nodeStatuses: Record<string, NodeStatus> = {};
  const edgeDecisions: Record<string, EdgeDecision> = {};

  if (runState) {
    for (const node of PIPELINE_NODES) {
      nodeStatuses[node] = deriveNodeStatus(node, runState);
    }
    Object.assign(edgeDecisions, deriveEdgeDecisions(runState));
  } else {
    for (const node of PIPELINE_NODES) {
      nodeStatuses[node] = 'ready';
    }
  }

  return { nodeStatuses, edgeDecisions, recentTransitions, runState, isPolling, error, connectionLost };
}
