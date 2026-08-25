import {
  Supplier,
  AttestationCycle,
  Assessment,
  FollowUpLetter,
  ProgrammeReport,
  ReviewDecision,
} from "../types";
import { config, buildApiUrl } from "../config";

export const api = {
  // Suppliers
  async getSuppliers(): Promise<Supplier[]> {
    const res = await fetch(buildApiUrl(config.api.endpoints.suppliers));
    if (!res.ok) throw new Error("Failed to fetch suppliers");
    return res.json();
  },

  async createSupplier(data: Omit<Supplier, "id" | "created_at" | "updated_at">): Promise<Supplier> {
    const res = await fetch(buildApiUrl(config.api.endpoints.suppliers), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error("Failed to create supplier");
    return res.json();
  },

  // Issuance & Cycles
  async getCycles(cycleYear: number = config.app.defaultCycleYear): Promise<AttestationCycle[]> {
    const res = await fetch(`${buildApiUrl(config.api.endpoints.cycles)}?cycle_year=${cycleYear}`);
    if (!res.ok) throw new Error("Failed to fetch attestation cycles");
    return res.json();
  },

  async issueQuestionnaire(supplierId: string, cycleYear: number = config.app.defaultCycleYear): Promise<any> {
    const res = await fetch(buildApiUrl(config.api.endpoints.issue), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ supplier_id: supplierId, cycle_year: cycleYear }),
    });
    if (!res.ok) throw new Error("Failed to issue questionnaire");
    return res.json();
  },

  // Ingestion
  async uploadResponse(attestationId: string, file: File, autoNormalize: boolean = true): Promise<any> {
    const formData = new FormData();
    formData.append("attestation_id", attestationId);
    formData.append("file", file);
    formData.append("auto_normalize", String(autoNormalize));

    const res = await fetch(buildApiUrl(config.api.endpoints.ingestUpload), {
      method: "POST",
      body: formData,
    });
    if (!res.ok) throw new Error("Failed to upload supplier response");
    return res.json();
  },

  // Assessments & Review Gate
  async getAssessmentByAttestation(attestationId: string): Promise<Assessment | null> {
    try {
      const res = await fetch(buildApiUrl(config.api.endpoints.assessmentsByAttestation(attestationId)));
      if (res.status === 404) return null;
      if (!res.ok) throw new Error("Failed to fetch assessment");
      return res.json();
    } catch {
      return null;
    }
  },

  async submitReview(
    assessmentId: string,
    isApproved: boolean,
    approvedBy: string,
    findingDecisions: Array<{ finding_id: string; review_decision: ReviewDecision; review_notes?: string }>
  ): Promise<Assessment> {
    const res = await fetch(buildApiUrl(config.api.endpoints.reviewSubmit(assessmentId)), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        is_approved: isApproved,
        approved_by: approvedBy,
        finding_decisions: findingDecisions,
      }),
    });
    if (!res.ok) throw new Error("Failed to submit review decisions");
    return res.json();
  },

  // Follow-up Letters
  async generateFollowUpLetter(
    attestationId: string,
    deadlineDays: number = config.app.defaultRemediationDays
  ): Promise<FollowUpLetter> {
    const res = await fetch(buildApiUrl(config.api.endpoints.followUpGenerate), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        attestation_id: attestationId,
        custom_remediation_deadline_days: deadlineDays,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Failed to generate follow-up letter" }));
      throw new Error(err.detail || "Failed to generate follow-up letter");
    }
    return res.json();
  },

  async getLettersByAttestation(attestationId: string): Promise<FollowUpLetter[]> {
    const res = await fetch(buildApiUrl(config.api.endpoints.followUpsByAttestation(attestationId)));
    if (!res.ok) throw new Error("Failed to fetch follow-up letters");
    return res.json();
  },

  async updateLetterStatus(letterId: string, status: "DRAFT" | "APPROVED" | "SENT"): Promise<FollowUpLetter> {
    const res = await fetch(buildApiUrl(config.api.endpoints.followUpStatus(letterId)), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!res.ok) throw new Error("Failed to update letter status");
    return res.json();
  },

  // Reports
  async getProgrammeReport(cycleYear: number = config.app.defaultCycleYear): Promise<ProgrammeReport> {
    const res = await fetch(buildApiUrl(config.api.endpoints.programmeReport(cycleYear)));
    if (!res.ok) throw new Error("Failed to fetch programme report");
    return res.json();
  },
};
