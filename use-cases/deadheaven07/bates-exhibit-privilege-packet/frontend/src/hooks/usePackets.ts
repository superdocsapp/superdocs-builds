import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { packetsApi } from '../services/packets';
import type { CreatePacketRequest } from '../types/api';

export function usePackets() {
  return useQuery({
    queryKey: ['packets'],
    queryFn: () => packetsApi.list(),
  });
}

export function usePacket(id: string) {
  return useQuery({
    queryKey: ['packets', id],
    queryFn: () => packetsApi.get(id),
    enabled: !!id,
  });
}

export function useCreatePacket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CreatePacketRequest) => packetsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['packets'] });
    },
  });
}

export function useUpdatePacket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<CreatePacketRequest> }) => packetsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['packets'] });
    },
  });
}

export function useDeletePacket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => packetsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['packets'] });
    },
  });
}