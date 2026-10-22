import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { batesApi } from '../services/bates';

export function useBatesAssignments(packetId: string) {
  return useQuery({
    queryKey: ['bates', 'assignments', packetId],
    queryFn: () => batesApi.getAssignments(packetId),
    enabled: !!packetId,
  });
}

export function useBatesPreview(packetId: string) {
  return useQuery({
    queryKey: ['bates', 'preview', packetId],
    queryFn: () => batesApi.preview(packetId),
    enabled: !!packetId,
  });
}

export function useAssignBates() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (packetId: string) => batesApi.assign(packetId),
    onSuccess: (_, packetId) => {
      queryClient.invalidateQueries({ queryKey: ['bates', 'assignments', packetId] });
      queryClient.invalidateQueries({ queryKey: ['bates', 'preview', packetId] });
    },
  });
}

export function useFinalizeBates() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (packetId: string) => batesApi.finalize(packetId),
    onSuccess: (_, packetId) => {
      queryClient.invalidateQueries({ queryKey: ['bates', 'assignments', packetId] });
    },
  });
}