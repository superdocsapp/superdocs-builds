import { apiClient } from './client'

export interface KnowledgeEntry {
  id: string
  workspace_id: string
  workflow_type: string
  entry_type: string
  content: string
  confidence_score: number | null
  tags: string[]
  source_run_id: string | null
  created_at: string
}

export interface CreateKnowledgeEntryRequest {
  workflow_type: string
  entry_type: string
  content: string
  confidence_score?: number
  tags?: string[]
  source_run_id?: string
}

function normalizeEntry(raw: Partial<KnowledgeEntry>): KnowledgeEntry {
  return {
    id: String(raw.id ?? ''),
    workspace_id: String(raw.workspace_id ?? ''),
    workflow_type: raw.workflow_type ?? '',
    entry_type: raw.entry_type ?? '',
    content: raw.content ?? '',
    confidence_score: raw.confidence_score ?? null,
    tags: Array.isArray(raw.tags) ? raw.tags : [],
    source_run_id: raw.source_run_id ?? null,
    created_at: raw.created_at ?? new Date().toISOString(),
  }
}

export const knowledgeApi = {
  listByWorkspace: async (
    workspaceId: string,
    params?: { workflow_type?: string; tags?: string; limit?: number }
  ): Promise<KnowledgeEntry[]> => {
    const response = await apiClient.get<Partial<KnowledgeEntry>[]>(
      `/knowledge/workspace/${workspaceId}`,
      { params }
    )
    const payload = response.data
    if (!Array.isArray(payload)) {
      throw new Error('Unexpected knowledge response format')
    }
    return payload.map(normalizeEntry)
  },

  create: async (workspaceId: string, data: CreateKnowledgeEntryRequest): Promise<KnowledgeEntry> => {
    const response = await apiClient.post<Partial<KnowledgeEntry>>(`/knowledge/workspace/${workspaceId}`, data)
    return normalizeEntry(response.data)
  },

  delete: async (workspaceId: string, entryId: string): Promise<void> => {
    await apiClient.delete(`/knowledge/workspace/${workspaceId}/entry/${entryId}`)
  }
}
