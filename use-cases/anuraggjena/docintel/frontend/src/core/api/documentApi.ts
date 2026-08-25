import { apiClient } from './client'

export interface Document {
  id: string
  workspace_id: string
  filename: string
  mime_type: string
  processing_status: string
  document_role?: string
  created_at: string
}

export type DocumentRole = 'product_spec' | 'ruling' | 'product_image' | 'other'

export const documentApi = {
  upload: async (
    workspaceId: string,
    file: File,
    role: DocumentRole = 'product_spec',
  ): Promise<Document> => {
    const formData = new FormData()
    formData.append('workspace_id', workspaceId)
    formData.append('file', file)
    formData.append('role', role)

    const response = await apiClient.post<Document>('/documents', formData)
    return response.data
  },

  list: async (workspaceId: string): Promise<Document[]> => {
    const response = await apiClient.get<Document[]>(`/documents/workspace/${workspaceId}`)
    return response.data
  },

  get: async (documentId: string): Promise<Document> => {
    const response = await apiClient.get<Document>(`/documents/${documentId}`)
    return response.data
  },

  download: async (documentId: string, filename: string): Promise<void> => {
    const response = await apiClient.get(`/documents/${documentId}/content`, {
      responseType: 'blob',
    })

    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    link.parentNode?.removeChild(link)
    window.URL.revokeObjectURL(url)
  },

  getContentBlob: async (documentId: string): Promise<Blob> => {
    const response = await apiClient.get(`/documents/${documentId}/content`, {
      responseType: 'blob',
    })
    return response.data
  },

  delete: async (documentId: string): Promise<void> => {
    await apiClient.delete(`/documents/${documentId}`)
  },
}
