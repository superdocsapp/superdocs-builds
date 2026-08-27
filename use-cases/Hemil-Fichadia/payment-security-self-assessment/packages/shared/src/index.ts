export const EVIDENCE_STATUSES = [
  "IMPLEMENTED",
  "PLANNED",
  "UNKNOWN",
] as const;

export type EvidenceStatus = (typeof EVIDENCE_STATUSES)[number];

export const EVIDENCE_CATEGORIES = {
  AUTHENTICATION: "Authentication",
  ACCESS_CONTROL: "Access Control",
  ENCRYPTION: "Encryption",
  LOGGING_AND_MONITORING: "Logging & Monitoring",
  INCIDENT_RESPONSE: "Incident Response",
} as const;

export type EvidenceCategoryId = keyof typeof EVIDENCE_CATEGORIES;

export interface EvidenceFact {
  id: string;
  category: EvidenceCategoryId;
  statement: string;
  status: EvidenceStatus;
  sourceDocumentId: string;
  sourceDocumentName: string;
  sourceReference?: string;
}

export function isEvidenceStatus(value: unknown): value is EvidenceStatus {
  return typeof value === "string" && EVIDENCE_STATUSES.includes(value as EvidenceStatus);
}

export function isEvidenceCategoryId(value: unknown): value is EvidenceCategoryId {
  return typeof value === "string" && value in EVIDENCE_CATEGORIES;
}

export function parseEvidenceFacts(value: unknown): EvidenceFact[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 100) {
    throw new Error("Provide between 1 and 100 evidence facts.");
  }

  return value.map((fact) => {
    if (
      typeof fact !== "object" ||
      fact === null ||
      !isEvidenceCategoryId(fact.category) ||
      !isEvidenceStatus(fact.status) ||
      typeof fact.id !== "string" ||
      typeof fact.statement !== "string" ||
      typeof fact.sourceDocumentId !== "string" ||
      typeof fact.sourceDocumentName !== "string" ||
      (fact.sourceReference !== undefined && typeof fact.sourceReference !== "string")
    ) {
      throw new Error("Evidence facts have an invalid shape.");
    }

    return {
      id: fact.id,
      category: fact.category,
      statement: fact.statement,
      status: fact.status,
      sourceDocumentId: fact.sourceDocumentId,
      sourceDocumentName: fact.sourceDocumentName,
      ...(fact.sourceReference === undefined ? {} : { sourceReference: fact.sourceReference }),
    };
  });
}
