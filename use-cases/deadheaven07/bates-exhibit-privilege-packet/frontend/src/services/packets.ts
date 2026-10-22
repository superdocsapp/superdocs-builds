import api from './api';
import type { Packet, CreatePacketRequest } from '../types/api';

export const packetsApi = {
  list: () => api.get<Packet[]>('/packets').then((r) => r.data),
  
  get: (id: string) => api.get<Packet>(`/packets/${id}`).then((r) => r.data),
  
  create: (data: CreatePacketRequest) => api.post<Packet>('/packets', data).then((r) => r.data),
  
  update: (id: string, data: Partial<CreatePacketRequest>) => api.patch<Packet>(`/packets/${id}`, data).then((r) => r.data),
  
  delete: (id: string) => api.delete(`/packets/${id}`).then((r) => r.data),
  
  reorder: (id: string, documentIds: string[]) => api.post(`/packets/${id}/reorder`, { document_ids: documentIds }).then((r) => r.data),
};