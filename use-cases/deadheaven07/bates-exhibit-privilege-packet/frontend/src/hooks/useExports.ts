import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { exportsApi } from '../services/exports';

export function useManifest(packetId: string) {
  return useQuery({
    queryKey: ['exports', 'manifest', packetId],
    queryFn: () => exportsApi.getManifest(packetId),
    enabled: !!packetId,
  });
}

export function useExhibits(packetId: string) {
  return useQuery({
    queryKey: ['exports', 'exhibits', packetId],
    queryFn: () => exportsApi.listExhibits(packetId),
    enabled: !!packetId,
  });
}

export function useBuildPacket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (packetId: string) => exportsApi.build(packetId),
    onSuccess: (_, packetId) => {
      queryClient.invalidateQueries({ queryKey: ['exports', 'manifest', packetId] });
      queryClient.invalidateQueries({ queryKey: ['exports', 'exhibits', packetId] });
    },
  });
}

export function useValidatePacket() {
  return useMutation({
    mutationFn: (packetId: string) => exportsApi.validate(packetId),
  });
}

export function useVerifyPacket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (packetId: string) => exportsApi.verify(packetId),
    onSuccess: (_, packetId) => {
      queryClient.invalidateQueries({ queryKey: ['exports', 'verify', packetId] });
    },
  });
}

export function useDownloadPacket(packetId: string) {
  return useMutation({
    mutationFn: () => exportsApi.download(packetId),
  });
}

export function useDownloadComponent(packetId: string, fileType: 'exhibit_index' | 'privilege_log') {
  return useMutation({
    mutationFn: () => exportsApi.downloadComponent(packetId, fileType),
  });
}