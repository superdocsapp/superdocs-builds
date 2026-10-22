import api from './api';
import type { DocumentListResponse, DocumentDetailResponse, UploadDocumentResponse } from '../types/api';

export const documentsApi = {
  upload: (packetId: string, files: FileList) => {
    const formData = new FormData();
    Array.from(files).forEach((file) => {
      formData.append('files', file);
    });
    return api.post<{ documents: UploadDocumentResponse[] }>(`/documents/${packetId}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then((r) => r.data);
  },

  list: (packetId: string) => api.get<DocumentListResponse[]>(`/documents/${packetId}`).then((r) => r.data),

  get: (packetId: string, documentId: string) => api.get<DocumentDetailResponse>(`/documents/${packetId}/${documentId}`).then((r) => r.data),

  delete: (packetId: string, documentId: string) => api.delete(`/documents/${packetId}/${documentId}`).then((r) => r.data),

  download: (packetId: string, documentId: string) => api.get(`/documents/${packetId}/${documentId}/download`, {
    responseType: 'blob',
  }).then((r) => r.data),

  reorder: (packetId: string, documentId: string, newOrder: number) => 
    api.patch(`/documents/${packetId}/${documentId}/reorder`, { new_order: newOrder }).then((r) => r.data),
};