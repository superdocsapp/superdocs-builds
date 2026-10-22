import api from './api';
import type { ProcessingStatusResponse, ProcessingDocumentStatus } from '../types/api';

export const processingApi = {
  start: (packetId: string) => api.post(`/processing/${packetId}/start`).then((r) => r.data),

  getPacketStatus: (packetId: string) => api.get<ProcessingStatusResponse>(`/processing/${packetId}/status`).then((r) => r.data),

  getDocumentStatus: (packetId: string, documentId: string) => api.get<ProcessingDocumentStatus>(`/processing/${packetId}/${documentId}/status`).then((r) => r.data),

  retry: (packetId: string, documentId: string) => api.post(`/processing/${packetId}/${documentId}/retry`).then((r) => r.data),
};