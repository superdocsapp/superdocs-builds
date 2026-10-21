import { apiClient } from './client'

export interface DiffToken {
  type: 'equal' | 'insert' | 'delete'
  text: string
}

export interface FormattingItem {
  id: string
  element_index: number
  element_type: string
  scene_number: number | null
  character_name: string | null
  original_text: string
  formatted_text: string
  change_type: string
  reason: string | null
  diff_tokens: DiffToken[] | null
  content_drift: boolean
  status: 'pending' | 'approved' | 'rejected'
  reviewer_comment: string | null
  confidence_score: number | null
  created_at: string
  updated_at: string
}

export interface PreviewResponse {
  original_text: string
  formatted_text: string
  item_count: number
  pending_count: number
  approved_count: number
  rejected_count: number
}

export interface ScreenplayLibraryItem {
  id: string
  workspace_id: string
  workspace_name: string
  filename: string
  mime_type: string
  processing_status: string
  created_at: string
  run_id?: string | null
  run_status?: string | null
  scenes_count?: number | null
  items_count?: number | null
  pending_items_count?: number | null
}

export const screenplayApi = {
  getLibrary: (): Promise<ScreenplayLibraryItem[]> =>
    apiClient.get('/screenplay/library').then(r => r.data),

  listItems: (runId: string): Promise<FormattingItem[]> =>
    apiClient.get(`/screenplay/${runId}/formatting-items`).then(r => r.data),

  getItem: (runId: string, itemId: string): Promise<FormattingItem> =>
    apiClient.get(`/screenplay/${runId}/formatting-items/${itemId}`).then(r => r.data),

  approveItem: (runId: string, itemId: string): Promise<FormattingItem> =>
    apiClient.post(`/screenplay/${runId}/formatting-items/${itemId}/approve`).then(r => r.data),

  rejectItem: (runId: string, itemId: string, reviewer_comment?: string): Promise<FormattingItem> =>
    apiClient
      .post(`/screenplay/${runId}/formatting-items/${itemId}/reject`, { reviewer_comment })
      .then(r => r.data),

  approveAll: (runId: string): Promise<{ approved_count: number }> =>
    apiClient.post(`/screenplay/${runId}/formatting-items/approve-all`).then(r => r.data),

  regenerate: (runId: string): Promise<{ run_id: string; queued: boolean }> =>
    apiClient.post(`/screenplay/${runId}/regenerate`).then(r => r.data),

  preview: (runId: string): Promise<PreviewResponse> =>
    apiClient.get(`/screenplay/${runId}/preview`).then(r => r.data),
}
