import { apiClient } from './client'
import type { WorkflowRun, WorkflowStage } from './types'

export const runsApi = {
  list: async (workspaceId: string): Promise<WorkflowRun[]> => {
    const response = await apiClient.get<WorkflowRun[]>(`/workspaces/${workspaceId}/runs`)
    return response.data
  },

  get: async (workspaceId: string, runId: string): Promise<WorkflowRun> => {
    const response = await apiClient.get<WorkflowRun>(`/workspaces/${workspaceId}/runs/${runId}`)
    return response.data
  },

  create: async (workspaceId: string, data: { workflow_slug: string; document_id: string; created_by?: string }): Promise<WorkflowRun> => {
    const response = await apiClient.post<WorkflowRun>(`/workspaces/${workspaceId}/runs`, data)
    return response.data
  },

  getStages: async (workspaceId: string, runId: string): Promise<WorkflowStage[]> => {
    const response = await apiClient.get<WorkflowStage[]>(`/workspaces/${workspaceId}/runs/${runId}/stages`)
    return response.data
  },

  resume: async (workspaceId: string, runId: string): Promise<WorkflowRun> => {
    const response = await apiClient.post<WorkflowRun>(`/workspaces/${workspaceId}/runs/${runId}/resume`)
    return response.data
  },

  cancel: async (workspaceId: string, runId: string): Promise<WorkflowRun> => {
    const response = await apiClient.post<WorkflowRun>(`/workspaces/${workspaceId}/runs/${runId}/cancel`)
    return response.data
  },

  replay: async (workspaceId: string, runId: string): Promise<WorkflowRun> => {
    const response = await apiClient.post<WorkflowRun>(`/workspaces/${workspaceId}/runs/${runId}/replay`)
    return response.data
  },

  getClaims: async (workspaceId: string, runId: string): Promise<RunClaim[]> => {
    const response = await apiClient.get<RunClaim[]>(`/workspaces/${workspaceId}/runs/${runId}/claims`)
    return response.data
  },

  approveAllClaims: async (
    workspaceId: string,
    runId: string
  ): Promise<{ approved_count: number; total_claims: number; resumed: boolean; run_id: string }> => {
    const response = await apiClient.post<{
      approved_count: number
      total_claims: number
      resumed: boolean
      run_id: string
    }>(`/workspaces/${workspaceId}/runs/${runId}/claims/approve-all`)
    return response.data
  },
}

export interface RunClaim {
  id: string
  claim_type: string
  content: string
  status: string
  source_stage: string | null
  confidence_score: string | null
  original_content: string | null
  review_id: string | null
  created_at: string | null
}
