import api from './api';
import type { AIAnalysisRequest, ApproveChangesRequest, ContinueJobRequest, AnalysisStatusResponse } from '../types/api';

export const reviewApi = {
  requestAnalysis: (packetId: string, documentId: string, data: AIAnalysisRequest) => 
    api.post(`/review/${packetId}/documents/${documentId}/analyze`, data).then((r) => r.data),

  getAnalysisStatus: (packetId: string, documentId: string, jobId: string) => 
    api.get<AnalysisStatusResponse>(`/review/${packetId}/documents/${documentId}/analysis-status?job_id=${jobId}`).then((r) => r.data),

  approveChanges: (packetId: string, documentId: string, data: ApproveChangesRequest) => 
    api.post(`/review/${packetId}/documents/${documentId}/approve-changes`, data).then((r) => r.data),

  continueJob: (packetId: string, documentId: string, data: ContinueJobRequest) => 
    api.post(`/review/${packetId}/documents/${documentId}/continue-job`, data).then((r) => r.data),

  export: (packetId: string, documentId: string, format?: string, options?: any) => 
    api.post(`/review/${packetId}/documents/${documentId}/export`, { format, options }).then((r) => r.data),

  getHistory: (packetId: string, documentId: string) => 
    api.get(`/review/${packetId}/documents/${documentId}/history`).then((r) => r.data),

  getPacketAIChanges: (packetId: string) => api.get(`/review/${packetId}/ai-changes`).then((r) => r.data),
};