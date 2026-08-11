import type { Dossier, DossierFinding, Document, AccessibilityAudit, AccessibilityRemediationResponse, DossierMetrics } from './types';

const API_BASE = '/api/v1';

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorMsg = 'An error occurred';
    try {
      const data = await response.json();
      errorMsg = data.detail || JSON.stringify(data);
    } catch {
      errorMsg = response.statusText || `HTTP error ${response.status}`;
    }
    throw new Error(errorMsg);
  }
  if (response.status === 204) {
    return null as T;
  }
  return response.json();
}

export const api = {
  // Dossier APIs
  async getDossiers(): Promise<Dossier[]> {
    const res = await fetch(`${API_BASE}/dossiers`);
    return handleResponse<Dossier[]>(res);
  },

  async createDossier(name: string): Promise<Dossier> {
    const res = await fetch(`${API_BASE}/dossiers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    return handleResponse<Dossier>(res);
  },

  async addQuestions(dossierId: string, questions: string[]): Promise<Dossier> {
    const res = await fetch(`${API_BASE}/dossiers/${dossierId}/questions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ questions }),
    });
    return handleResponse<Dossier>(res);
  },

  async runDossier(dossierId: string): Promise<Dossier> {
    const res = await fetch(`${API_BASE}/dossiers/${dossierId}/run`, {
      method: 'POST',
    });
    return handleResponse<Dossier>(res);
  },

  async getDossier(dossierId: string): Promise<Dossier> {
    const res = await fetch(`${API_BASE}/dossiers/${dossierId}`);
    return handleResponse<Dossier>(res);
  },

  async getDossierFinding(dossierId: string, findingId: string): Promise<DossierFinding> {
    const res = await fetch(`${API_BASE}/dossiers/${dossierId}/findings/${findingId}`);
    return handleResponse<DossierFinding>(res);
  },

  async approveFinding(dossierId: string, findingId: string): Promise<DossierFinding> {
    const res = await fetch(`${API_BASE}/dossiers/${dossierId}/findings/${findingId}/approve`, {
      method: 'POST',
    });
    return handleResponse<DossierFinding>(res);
  },

  async rejectFinding(dossierId: string, findingId: string, reason: string): Promise<DossierFinding> {
    const res = await fetch(`${API_BASE}/dossiers/${dossierId}/findings/${findingId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    });
    return handleResponse<DossierFinding>(res);
  },

  async editFinding(
    dossierId: string,
    findingId: string,
    answer: string,
    reasoningSummary: string
  ): Promise<DossierFinding> {
    const res = await fetch(`${API_BASE}/dossiers/${dossierId}/findings/${findingId}/edit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer, reasoning_summary: reasoningSummary }),
    });
    return handleResponse<DossierFinding>(res);
  },

  async retryFinding(dossierId: string, findingId: string): Promise<DossierFinding> {
    const res = await fetch(`${API_BASE}/dossiers/${dossierId}/findings/${findingId}/retry`, {
      method: 'POST',
    });
    return handleResponse<DossierFinding>(res);
  },

  // Document APIs
  async getDocuments(): Promise<Document[]> {
    const res = await fetch(`${API_BASE}/documents`);
    return handleResponse<Document[]>(res);
  },

  async uploadDocument(file: File): Promise<Document> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/documents/upload`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse<Document>(res);
  },

  async deleteDocument(documentId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/documents/${documentId}`, {
      method: 'DELETE',
    });
    return handleResponse<void>(res);
  },

  // Accessibility Tool APIs
  async checkAccessibilityText(text: string): Promise<AccessibilityAudit> {
    const res = await fetch(`${API_BASE}/accessibility/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    return handleResponse<AccessibilityAudit>(res);
  },

  async checkAccessibility(file: File): Promise<AccessibilityAudit> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/accessibility/check-file`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse<AccessibilityAudit>(res);
  },

  async remediateAccessibility(text: string, altTextOverrides: Record<string, string>): Promise<AccessibilityRemediationResponse> {
    const res = await fetch(`${API_BASE}/accessibility/remediate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, alt_text_overrides: altTextOverrides }),
    });
    return handleResponse<AccessibilityRemediationResponse>(res);
  },
  
  async exportDossier(dossierId: string): Promise<string> {
    const res = await fetch(`${API_BASE}/dossiers/${dossierId}/export`);
    if (!res.ok) {
      throw new Error(`Failed to export dossier: ${res.statusText}`);
    }
    return res.text();
  },

  async getDossierMetrics(dossierId: string): Promise<DossierMetrics> {
    const res = await fetch(`${API_BASE}/dossiers/${dossierId}/metrics`);
    return handleResponse<DossierMetrics>(res);
  },
};
