import { apiClient } from './client'

export interface Export {
  id: string
  workspace_id: string
  workflow_run_id: string | null
  review_id: string | null
  filename: string
  format: string
  file_size: number
  exported_by: string | null
  created_at: string
}

export interface CreateExportRequest {
  review_id: string
  exported_by?: string
  format?: 'docx' | 'pdf'
}

export interface RunExportResponse {
  export_id: string
  filename: string
}

export const exportApi = {
  create: async (data: CreateExportRequest): Promise<Export> => {
    const response = await apiClient.post<Export>('/exports', data)
    return response.data
  },

  exportRun: async (
    workspaceId: string,
    runId: string,
    workflowSlug?: string,
    format: 'docx' | 'pdf' = 'docx'
  ): Promise<RunExportResponse> => {
    const slug = workflowSlug === 'screenplay' ? 'screenplay' : 'tariff'
    const response = await apiClient.post<RunExportResponse>(
      `/exports/${slug}/${runId}?workspace_id=${workspaceId}&format=${format}`
    )
    return response.data
  },

  get: async (exportId: string): Promise<Export> => {
    const response = await apiClient.get<Export>(`/exports/${exportId}`)
    return response.data
  },

  download: async (exportId: string, filename: string): Promise<void> => {
    const response = await apiClient.get(`/exports/${exportId}/download`, {
      responseType: 'blob',
    })
    const isPdf = filename.toLowerCase().endsWith('.pdf')
    const mimeType = isPdf
      ? 'application/pdf'
      : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    const blob = new Blob([response.data], { type: mimeType })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    setTimeout(() => {
      link.parentNode?.removeChild(link)
      window.URL.revokeObjectURL(url)
    }, 100)
  },

  listByWorkspace: async (workspaceId: string): Promise<Export[]> => {
    const response = await apiClient.get<Export[]>(`/exports/workspace/${workspaceId}`)
    return response.data
  },
}


