import api from './api';
import type { BatesPreviewResponse } from '../types/api';

export const batesApi = {
  assign: (packetId: string) => api.post(`/bates/${packetId}/assign`).then((r) => r.data),

  getAssignments: (packetId: string) => api.get(`/bates/${packetId}`).then((r) => r.data),

  preview: (packetId: string) => api.get<BatesPreviewResponse>(`/bates/${packetId}/preview`).then((r) => r.data),

  finalize: (packetId: string) => api.post(`/bates/${packetId}/finalize`).then((r) => r.data),
};