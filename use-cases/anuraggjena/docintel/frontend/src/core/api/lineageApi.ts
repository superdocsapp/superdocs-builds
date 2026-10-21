import { apiClient } from './client'

// ============================================================================
// Type Definitions
// ============================================================================

export interface LineageNode {
  id: string
  type: string
  label: string
  metadata?: Record<string, any>
}

export interface LineageEdge {
  source_id: string
  target_id: string
  edge_type: string
  metadata?: Record<string, any>
}

export interface LineageGraph {
  nodes: LineageNode[]
  edges: LineageEdge[]
  root_node_id: string | null
}

export interface KnowledgeProvenance {
  knowledge_entry_id: string
  source_run_id: string
  content: string
  relevance_score?: number
  adoption_reason?: string
  created_at: string
}

export interface ReplayStage {
  stage_name: string
  status: string
  started_at?: string
  completed_at?: string
  execution_time_ms?: number
  inputs?: Record<string, any>
  outputs?: Record<string, any>
  contributed_to_claim?: boolean
}

export interface ReplayTimeline {
  run_id: string
  stages: ReplayStage[]
  knowledge_reused: any[]
  review_decisions: any[]
}

export interface Claim {
  id: string
  content: string
  status: string
  claim_type: string
  workflow_run_id: string
  confidence_score?: number
  created_at: string
  updated_at: string
}

// ============================================================================
// API Functions
// ============================================================================

export const lineageApi = {
  /**
   * Get the lineage graph for a specific claim
   * @param claimId - The ID of the claim
   * @param depth - How many levels deep to traverse (default: 3)
   */
  getClaimLineage: (claimId: string, depth: number = 3): Promise<LineageGraph> =>
    apiClient.get(`/lineage/claim/${claimId}`, { params: { depth } }).then(r => r.data),

  /**
   * Get the lineage graph for a specific workflow run
   * @param runId - The ID of the workflow run
   */
  getRunLineage: (runId: string): Promise<LineageGraph> =>
    apiClient.get(`/lineage/run/${runId}`).then(r => r.data),

  /**
   * Get knowledge provenance for a specific claim
   * Shows which knowledge entries from previous runs contributed to this claim
   * @param claimId - The ID of the claim
   */
  getClaimKnowledgeProvenance: (claimId: string): Promise<KnowledgeProvenance[]> =>
    apiClient.get(`/lineage/claim/${claimId}/knowledge`).then(r => r.data),

  /**
   * Get the regeneration chain for a specific claim
   * Shows all versions of a claim across regenerations
   * @param claimId - The ID of the claim
   */
  getClaimRegenerationChain: (claimId: string): Promise<Claim[]> =>
    apiClient.get(`/lineage/claim/${claimId}/regeneration-chain`).then(r => r.data),

  /**
   * Replay the execution that led to a specific claim
   * Shows detailed timeline of all stages and decisions
   * @param claimId - The ID of the claim
   */
  replayClaimExecution: (claimId: string): Promise<ReplayTimeline> =>
    apiClient.post(`/replay/claim/${claimId}`).then(r => r.data),

  /**
   * Replay the execution of a workflow run
   * Shows detailed timeline of all stages and decisions
   * @param runId - The ID of the workflow run
   */
  replayRunExecution: (runId: string): Promise<ReplayTimeline> =>
    apiClient.get(`/replay/run/${runId}`).then(r => r.data),
}
