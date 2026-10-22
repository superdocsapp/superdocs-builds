import api from './api';
import type { SearchResponse, BatesSearchResponse } from '../types/api';

export const searchApi = {
  searchPacket: (packetId: string, q: string) =>
    api.get<SearchResponse>(`/search/${packetId}`, { params: { q } }).then((r) => r.data),

  searchByBates: (packetId: string, batesNumber: string) =>
    api.get<BatesSearchResponse>(`/search/${packetId}/bates/${batesNumber}`).then((r) => r.data),
};