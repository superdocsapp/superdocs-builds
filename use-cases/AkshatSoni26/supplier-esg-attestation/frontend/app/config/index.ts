/**
 * Centralized Configuration for SuperDocs ESG Attestation Frontend
 * Eliminates all hardcoded URLs and values across the application.
 */

export const config = {
  api: {
    baseUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1",
    endpoints: {
      suppliers: "/suppliers",
      cycles: "/issuance/cycles",
      issue: "/issuance/issue",
      ingestUpload: "/ingestion/upload",
      assessmentsByAttestation: (attestationId: string) => `/assessments/by-attestation/${attestationId}`,
      reviewSubmit: (assessmentId: string) => `/review/${assessmentId}/submit`,
      followUpGenerate: "/follow-ups/generate",
      followUpsByAttestation: (attestationId: string) => `/follow-ups/by-attestation/${attestationId}`,
      followUpStatus: (letterId: string) => `/follow-ups/${letterId}/status`,
      programmeReport: (year: number) => `/reports/programme-summary?cycle_year=${year}`,
      downloadDocument: (docId: string, format: string = "pdf") => `/superdocs/download/${docId}.${format}`,
    },
  },
  app: {
    defaultCycleYear: 2026,
    defaultRemediationDays: 30,
    brandName: "SuperDocs",
    tagline: "AI Document Assistant for ESG Compliance",
    models: [
      { id: "core", name: "Core", description: "Fast & precise compliance audits" },
      { id: "balanced", name: "Balanced", description: "High reasoning & legal synthesis" },
      { id: "deep", name: "Deep Analysis", description: "Multi-jurisdiction trade & ESG verification" },
    ],
  },
} as const;

export const buildApiUrl = (path: string): string => {
  return `${config.api.baseUrl}${path}`;
};
