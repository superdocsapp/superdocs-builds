import api from './api';
import type { RedactionApprovalRequest, ApplyRedactionsRequest } from '../types/api';

export const redactionsApi = {
  detect: (packetId: string) => api.post(`/redactions/${packetId}/detect`).then((r) => r.data),

  getAll: (packetId: string) => api.get(`/redactions/${packetId}`).then((r) => r.data),

  getByDocument: (packetId: string, documentId: string) => api.get(`/redactions/${packetId}/${documentId}`).then((r) => r.data),

  approve: (redactionId: string, data: RedactionApprovalRequest) => api.post(`/redactions/${redactionId}/approve`, data).then((r) => r.data),

  reject: (redactionId: string, data: RedactionApprovalRequest) => api.post(`/redactions/${redactionId}/reject`, data).then((r) => r.data),

  apply: (redactionId: string) => api.post(`/redactions/${redactionId}/apply`).then((r) => r.data),

  applyAll: (packetId: string, data: ApplyRedactionsRequest) => api.post(`/redactions/${packetId}/apply-all`, data).then((r) => r.data),
};