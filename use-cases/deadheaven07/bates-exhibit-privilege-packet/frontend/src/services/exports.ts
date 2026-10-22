import api from './api';
import type { ValidationResponse, ManifestResponse, VerifyResponse } from '../types/api';

export const exportsApi = {
  build: (packetId: string) => api.post(`/exports/${packetId}/build`).then((r) => r.data),

  validate: (packetId: string) => api.post<ValidationResponse>(`/exports/${packetId}/validate`).then((r) => r.data),

  verify: (packetId: string) => api.post<VerifyResponse>(`/exports/${packetId}/verify`).then((r) => r.data),

  getManifest: (packetId: string) => api.get<ManifestResponse>(`/exports/${packetId}/manifest`).then((r) => r.data),

  download: (packetId: string) => api.get(`/exports/${packetId}/download`, { responseType: 'blob' }).then((r) => r.data),

  downloadComponent: (packetId: string, fileType: 'exhibit_index' | 'privilege_log') => 
    api.get(`/exports/${packetId}/download/${fileType}`, { responseType: 'blob' }).then((r) => r.data),

  listExhibits: (packetId: string) => api.get<{ exhibits: any[] }>(`/exports/${packetId}/exhibits`).then((r) => r.data),
};