import { apiClient } from './client'

export interface QualityGateConfig {
  id: string
  workspace_id: string
  enabled: boolean
  block_on_failure: boolean
  checks_config: Record<string, unknown>
  created_at: string
}

export interface QualityGateCheckDetail {
  check_name: string
  status: 'passed' | 'failed' | 'skipped' | 'warning'
  severity: 'error' | 'warning' | 'info'
  message: string
  details: Record<string, unknown>
  blocking: boolean
}

export interface QualityGateResult {
  id: string
  workflow_run_id: string
  status: 'passed' | 'failed' | 'warning' | 'skipped'
  checks_run: number
  checks_passed: number
  checks_failed: number
  blocking: boolean
  details: QualityGateCheckDetail[]
  created_at: string
}

export const qualityGateApi = {
  getConfig: async (workspaceId: string): Promise<QualityGateConfig | null> => {
    const response = await apiClient.get(`/quality-gate/workspace/${workspaceId}/config`)
    return response.data
  },

  upsertConfig: async (workspaceId: string, config: Partial<QualityGateConfig>): Promise<QualityGateConfig> => {
    const response = await apiClient.put(`/quality-gate/workspace/${workspaceId}/config`, config)
    return response.data
  },

  getRunResult: async (workflowRunId: string): Promise<QualityGateResult | null> => {
    const response = await apiClient.get(`/quality-gate/run/${workflowRunId}/result`)
    return response.data
  }
}
