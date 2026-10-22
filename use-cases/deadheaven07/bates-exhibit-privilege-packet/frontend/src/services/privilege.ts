import api from './api';
import type { PrivilegeDecisionRequest, PrivilegeLogResponse } from '../types/api';

export const privilegeApi = {
  getDecisions: (packetId: string) => api.get(`/privilege/${packetId}`).then((r) => r.data),

  markPrivilege: (packetId: string, documentId: string, data: PrivilegeDecisionRequest) => 
    api.post(`/privilege/${packetId}/${documentId}`, data).then((r) => r.data),

  updatePrivilege: (packetId: string, documentId: string, data: PrivilegeDecisionRequest) => 
    api.patch(`/privilege/${packetId}/${documentId}`, data).then((r) => r.data),

  getLog: (packetId: string) => api.get<PrivilegeLogResponse>(`/privilege/${packetId}/log`).then((r) => r.data),
};