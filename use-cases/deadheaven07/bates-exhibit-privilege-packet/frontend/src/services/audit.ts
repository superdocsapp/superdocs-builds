import api from './api';
import type { AuditTrailResponse } from '../types/api';

export const auditApi = {
  getTrail: (packetId: string): Promise<AuditTrailResponse> => api.get(`/audit/${packetId}`).then((r) => r.data),

  getDocumentAudit: (packetId: string, documentId: string): Promise<AuditTrailResponse> => api.get(`/audit/${packetId}/${documentId}`).then((r) => r.data),
};