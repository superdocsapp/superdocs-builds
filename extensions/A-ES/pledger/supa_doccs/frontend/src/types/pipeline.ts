export type NodeStatus = 'ready' | 'processing' | 'complete' | 'skipped' | 'escalated' | 'failed' | 'retrying';

export type EdgeDecision = 'next' | 'retry' | 'skip' | 'escalate';

export interface SkippedNode {
  node_name: string;
  reason: string;
}

export interface PipelineRunState {
  run_id: string;
  current_node: string;
  node_status: string; // "completed" | "skipped" | "error"
  completed_nodes: string[];
  skipped_nodes: SkippedNode[];
  retries: Record<string, number>;
  error_type: string | null;
  error_detail: string | null;
  run_status: 'running' | 'completed' | 'failed' | 'paused';
}

// All pipeline node names in execution order
export const PIPELINE_NODES = [
  'ingest',
  'extract_text',
  'classify_document',
  'chunk',
  'embed',
  'extract_claims',
  'match_rules',
  'match_rules_against_sources',
  'merge_findings',
  'score_confidence',
  'route_to_queue',
  'human_review',
  'finalize',
] as const;

export type PipelineNodeName = typeof PIPELINE_NODES[number];
