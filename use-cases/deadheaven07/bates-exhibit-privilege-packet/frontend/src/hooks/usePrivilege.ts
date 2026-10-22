import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { privilegeApi } from '../services/privilege';
import type { PrivilegeDecisionRequest } from '../types/api';

export function usePrivilegeDecisions(packetId: string) {
  return useQuery({
    queryKey: ['privilege', 'decisions', packetId],
    queryFn: () => privilegeApi.getDecisions(packetId),
    enabled: !!packetId,
  });
}

export function usePrivilegeLog(packetId: string) {
  return useQuery({
    queryKey: ['privilege', 'log', packetId],
    queryFn: () => privilegeApi.getLog(packetId),
    enabled: !!packetId,
  });
}

export function useMarkPrivilege() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ packetId, documentId, data }: { packetId: string; documentId: string; data: PrivilegeDecisionRequest }) => 
      privilegeApi.markPrivilege(packetId, documentId, data),
    onSuccess: (_, { packetId }) => {
      queryClient.invalidateQueries({ queryKey: ['privilege', 'decisions', packetId] });
      queryClient.invalidateQueries({ queryKey: ['privilege', 'log', packetId] });
    },
  });
}