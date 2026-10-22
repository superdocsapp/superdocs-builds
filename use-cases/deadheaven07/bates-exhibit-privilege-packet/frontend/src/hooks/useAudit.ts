import { useQuery } from '@tanstack/react-query';
import { auditApi } from '../services/audit';

export function useAuditTrail(packetId: string) {
  return useQuery({
    queryKey: ['audit', packetId],
    queryFn: () => auditApi.getTrail(packetId),
    enabled: !!packetId,
  });
}

export function useDocumentAudit(packetId: string, documentId: string) {
  return useQuery({
    queryKey: ['audit', 'document', packetId, documentId],
    queryFn: () => auditApi.getDocumentAudit(packetId, documentId),
    enabled: !!packetId && !!documentId,
  });
}