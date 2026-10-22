import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { documentsApi } from '../services/documents';

export function useDocuments(packetId: string) {
  return useQuery({
    queryKey: ['documents', packetId],
    queryFn: () => documentsApi.list(packetId),
    enabled: !!packetId,
  });
}

export function useDocument(packetId: string, documentId: string) {
  return useQuery({
    queryKey: ['documents', packetId, documentId],
    queryFn: () => documentsApi.get(packetId, documentId),
    enabled: !!packetId && !!documentId,
  });
}

export function useUploadDocuments(packetId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (files: FileList) => documentsApi.upload(packetId, files),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', packetId] });
    },
  });
}

export function useDeleteDocument(packetId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) => documentsApi.delete(packetId, documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', packetId] });
    },
  });
}

export function useReorderDocument(packetId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ documentId, newOrder }: { documentId: string; newOrder: number }) => 
      documentsApi.reorder(packetId, documentId, newOrder),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', packetId] });
    },
  });
}

export function useDownloadDocument(packetId: string) {
  return useMutation({
    mutationFn: (documentId: string) => documentsApi.download(packetId, documentId),
  });
}