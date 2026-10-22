import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { processingApi } from '../services/processing';

export function useProcessingStatus(packetId: string) {
  return useQuery({
    queryKey: ['processing', 'status', packetId],
    queryFn: () => processingApi.getPacketStatus(packetId),
    enabled: !!packetId,
    refetchInterval: 5000,
  });
}

export function useDocumentProcessingStatus(packetId: string, documentId: string) {
  return useQuery({
    queryKey: ['processing', 'document', packetId, documentId],
    queryFn: () => processingApi.getDocumentStatus(packetId, documentId),
    enabled: !!packetId && !!documentId,
    refetchInterval: 5000,
  });
}

export function useStartProcessing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (packetId: string) => processingApi.start(packetId),
    onSuccess: (_, packetId) => {
      queryClient.invalidateQueries({ queryKey: ['processing', 'status', packetId] });
    },
  });
}

export function useRetryDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ packetId, documentId }: { packetId: string; documentId: string }) => 
      processingApi.retry(packetId, documentId),
    onSuccess: (_, { packetId }) => {
      queryClient.invalidateQueries({ queryKey: ['processing', 'status', packetId] });
    },
  });
}