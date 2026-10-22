import { useQuery, useMutation } from '@tanstack/react-query';
import { reviewApi } from '../services/review';
import type { AIAnalysisRequest, ApproveChangesRequest, ContinueJobRequest } from '../types/api';

export function usePacketAIChanges(packetId: string) {
  return useQuery({
    queryKey: ['review', 'ai-changes', packetId],
    queryFn: () => reviewApi.getPacketAIChanges(packetId),
    enabled: !!packetId,
  });
}

export function useRequestAIAnalysis() {
  return useMutation({
    mutationFn: ({ packetId, documentId, data }: { packetId: string; documentId: string; data: AIAnalysisRequest }) => 
      reviewApi.requestAnalysis(packetId, documentId, data),
  });
}

export function useAnalysisStatus(packetId: string, documentId: string, jobId: string) {
  return useQuery({
    queryKey: ['review', 'status', packetId, documentId, jobId],
    queryFn: () => reviewApi.getAnalysisStatus(packetId, documentId, jobId),
    enabled: !!packetId && !!documentId && !!jobId,
    refetchInterval: 3000,
  });
}

export function useApproveAIChanges() {
  return useMutation({
    mutationFn: ({ packetId, documentId, data }: { packetId: string; documentId: string; data: ApproveChangesRequest }) => 
      reviewApi.approveChanges(packetId, documentId, data),
  });
}

export function useContinueAIJob() {
  return useMutation({
    mutationFn: ({ packetId, documentId, data }: { packetId: string; documentId: string; data: ContinueJobRequest }) => 
      reviewApi.continueJob(packetId, documentId, data),
  });
}

export function useExportSuperDocsDocument() {
  return useMutation({
    mutationFn: ({ packetId, documentId, format, options }: { packetId: string; documentId: string; format?: string; options?: any }) => 
      reviewApi.export(packetId, documentId, format, options),
  });
}