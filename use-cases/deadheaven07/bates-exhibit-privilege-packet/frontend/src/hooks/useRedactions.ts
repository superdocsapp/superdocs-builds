import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { redactionsApi } from '../services/redactions';
import type { ApplyRedactionsRequest } from '../types/api';

export function useRedactionCandidates(packetId: string) {
  return useQuery({
    queryKey: ['redactions', 'candidates', packetId],
    queryFn: () => redactionsApi.getAll(packetId),
    enabled: !!packetId,
  });
}

export function useDocumentRedactions(packetId: string, documentId: string) {
  return useQuery({
    queryKey: ['redactions', 'document', packetId, documentId],
    queryFn: () => redactionsApi.getByDocument(packetId, documentId),
    enabled: !!packetId && !!documentId,
  });
}

export function useDetectRedactions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (packetId: string) => redactionsApi.detect(packetId),
    onSuccess: (_, packetId) => {
      queryClient.invalidateQueries({ queryKey: ['redactions', 'candidates', packetId] });
    },
  });
}

export function useApproveRedaction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ redactionId, data }: { packetId: string; redactionId: string; data: { status: 'approved' | 'rejected'; approver: string } }) => 
      redactionsApi[data.status === 'approved' ? 'approve' : 'reject'](redactionId, data),
    onSuccess: (_, { packetId }) => {
      queryClient.invalidateQueries({ queryKey: ['redactions', 'candidates', packetId] });
    },
  });
}

export function useApplyRedaction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ packetId, redactionId }: { packetId: string; redactionId: string }) => 
      redactionsApi.apply(redactionId).then(() => ({ packetId })),
    onSuccess: ({ packetId }) => {
      queryClient.invalidateQueries({ queryKey: ['redactions', 'candidates', packetId] });
    },
  });
}

export function useApplyAllRedactions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ packetId, data }: { packetId: string; data: ApplyRedactionsRequest }) => 
      redactionsApi.applyAll(packetId, data),
    onSuccess: (_, { packetId }) => {
      queryClient.invalidateQueries({ queryKey: ['redactions', 'candidates', packetId] });
    },
  });
}