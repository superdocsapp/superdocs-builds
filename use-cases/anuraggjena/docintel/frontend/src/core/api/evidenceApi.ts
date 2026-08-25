import { apiClient } from './client'
import type { Evidence, Citation } from './types'

export const evidenceApi = {
  listForRun: async (workflowRunId: string): Promise<Evidence[]> => {
    const response = await apiClient.get<Evidence[]>(`/evidence/run/${workflowRunId}`)
    return response.data
  },

  listCitationsForRun: async (workflowRunId: string): Promise<Citation[]> => {
    const response = await apiClient.get<Citation[]>(`/evidence/run/${workflowRunId}/citations`)
    return response.data
  },
}
