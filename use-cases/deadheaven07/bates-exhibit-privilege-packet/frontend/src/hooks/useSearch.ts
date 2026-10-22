import { useQuery } from '@tanstack/react-query';
import { searchApi } from '../services/search';

export function useSearchPacket(packetId: string, query: string) {
  return useQuery({
    queryKey: ['search', packetId, query],
    queryFn: () => searchApi.searchPacket(packetId, query),
    enabled: !!packetId && query.trim().length > 0,
  });
}

export function useSearchByBates(packetId: string, batesNumber: string) {
  return useQuery({
    queryKey: ['search', 'bates', packetId, batesNumber],
    queryFn: () => searchApi.searchByBates(packetId, batesNumber),
    enabled: !!packetId && !!batesNumber,
    retry: false,
  });
}