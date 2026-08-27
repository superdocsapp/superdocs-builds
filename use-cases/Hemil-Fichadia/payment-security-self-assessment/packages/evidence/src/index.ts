import {
  EVIDENCE_CATEGORIES,
  EVIDENCE_STATUSES,
  type EvidenceCategoryId,
  type EvidenceFact,
  type EvidenceStatus,
} from "@payment-security-self-assessment/shared";

export {
  EVIDENCE_CATEGORIES,
  EVIDENCE_STATUSES,
  type EvidenceCategoryId,
  type EvidenceFact,
  type EvidenceStatus,
};

export type EvidenceFactsByCategory = Record<
  EvidenceCategoryId,
  Record<EvidenceStatus, EvidenceFact[]>
>;

export const SYNTHETIC_COMPANY = {
  id: "meridian-payments",
  name: "Meridian Payments",
} as const;

export const syntheticFintechEvidence: EvidenceFact[] = [
  {
    id: "auth-admin-mfa-enforced",
    category: "AUTHENTICATION",
    statement: "Administrator accounts currently require multi-factor authentication.",
    status: "IMPLEMENTED",
    sourceDocumentId: "identity-standard-2026",
    sourceDocumentName: "Identity and Access Standard",
    sourceReference: "Section 4.2",
  },
  {
    id: "auth-workforce-mfa-rollout",
    category: "AUTHENTICATION",
    statement: "Multi-factor authentication will be extended to all workforce accounts in Q4 2026.",
    status: "PLANNED",
    sourceDocumentId: "security-roadmap-2026",
    sourceDocumentName: "Security Improvement Roadmap",
    sourceReference: "Q4 2026 initiative",
  },
  {
    id: "access-quarterly-review-planned",
    category: "ACCESS_CONTROL",
    statement: "Quarterly access reviews are planned but have not started.",
    status: "PLANNED",
    sourceDocumentId: "security-roadmap-2026",
    sourceDocumentName: "Security Improvement Roadmap",
    sourceReference: "Q3 2026 initiative",
  },
  {
    id: "access-privileged-review-unknown",
    category: "ACCESS_CONTROL",
    statement: "The supplied evidence does not establish whether privileged access reviews currently occur.",
    status: "UNKNOWN",
    sourceDocumentId: "evidence-gap-register-2026",
    sourceDocumentName: "Evidence Gap Register",
    sourceReference: "Access governance",
  },
  {
    id: "encryption-payment-data-at-rest",
    category: "ENCRYPTION",
    statement: "Payment data is encrypted at rest in production systems.",
    status: "IMPLEMENTED",
    sourceDocumentId: "production-security-architecture",
    sourceDocumentName: "Production Security Architecture",
    sourceReference: "Data protection",
  },
  {
    id: "logging-retention-implemented",
    category: "LOGGING_AND_MONITORING",
    statement: "Security logs are retained for 90 days.",
    status: "IMPLEMENTED",
    sourceDocumentId: "security-logging-standard",
    sourceDocumentName: "Security Logging Standard",
    sourceReference: "Retention requirements",
  },
  {
    id: "logging-retention-increase-planned",
    category: "LOGGING_AND_MONITORING",
    statement: "Security log retention is planned to increase to one year in Q1 2027.",
    status: "PLANNED",
    sourceDocumentId: "security-roadmap-2026",
    sourceDocumentName: "Security Improvement Roadmap",
    sourceReference: "Q1 2027 initiative",
  },
  {
    id: "incident-response-process",
    category: "INCIDENT_RESPONSE",
    statement: "A documented incident-response process currently exists.",
    status: "IMPLEMENTED",
    sourceDocumentId: "incident-response-playbook",
    sourceDocumentName: "Incident Response Playbook",
    sourceReference: "Version 2.1",
  },
];

export interface ExtractedEvidenceDocument {
  id: string;
  name: string;
  text: string;
}

const categoryMatchers: Array<[EvidenceCategoryId, RegExp]> = [
  ["AUTHENTICATION", /\b(mfa|multi[- ]factor|authentication)\b/i],
  ["ACCESS_CONTROL", /\b(access reviews?|user access reviews?|privileged (?:access|accounts?)|access control|least privilege)\b/i],
  ["ENCRYPTION", /\b(backup encryption|encryption keys?|encrypt(?:ed|ion)?)\b/i],
  ["LOGGING_AND_MONITORING", /\b(logs?|logging|monitoring)\b/i],
  ["INCIDENT_RESPONSE", /\b(incident[- ]response|incident paging|tabletop incident[- ]response)\b/i],
];

export function classifyEvidenceStatement(
  statement: string,
): Pick<EvidenceFact, "category" | "status"> | undefined {
  const category = categoryMatchers.find(([, matcher]) => matcher.test(statement))?.[0];
  if (!category) return undefined;

  if (/\b(does not establish|unknown|insufficient evidence|no evidence was provided|not confirmed|cannot determine|cannot establish|cannot confirm)\b/i.test(statement)) {
    return { category, status: "UNKNOWN" };
  }
  if (/\b(planned|will be|scheduled|future|q[1-4]\s+20\d{2}|not started|not yet implemented)\b/i.test(statement)) {
    return { category, status: "PLANNED" };
  }
  if (/\b(currently|require[sd]?|enforced|encrypted|retained|exists|documented)\b/i.test(statement)) {
    return { category, status: "IMPLEMENTED" };
  }

  return undefined;
}

export function classifyExtractedEvidence(
  documents: readonly ExtractedEvidenceDocument[],
): EvidenceFact[] {
  return documents.flatMap((document) =>
    document.text.split(/\r?\n/).flatMap((line, index) => {
      const statement = line.trim();
      const classification = classifyEvidenceStatement(statement);
      if (!classification) return [];

      return [{
        id: `${document.id}-line-${index + 1}`,
        statement,
        ...classification,
        sourceDocumentId: document.id,
        sourceDocumentName: document.name,
        sourceReference: `Line ${index + 1}`,
      }];
    }),
  );
}

export function evidenceFactsMatchDeterministicClassification(
  facts: readonly EvidenceFact[],
): boolean {
  return facts.every((fact) => {
    const classification = classifyEvidenceStatement(fact.statement);
    return classification?.category === fact.category && classification.status === fact.status;
  });
}

export function filterEvidenceFacts(
  facts: readonly EvidenceFact[],
  filters: Partial<Pick<EvidenceFact, "category" | "status">>,
): EvidenceFact[] {
  return facts.filter(
    (fact) =>
      (filters.category === undefined || fact.category === filters.category) &&
      (filters.status === undefined || fact.status === filters.status),
  );
}

export function groupEvidenceFacts(
  facts: readonly EvidenceFact[],
): EvidenceFactsByCategory {
  const grouped = {} as EvidenceFactsByCategory;

  for (const category of Object.keys(EVIDENCE_CATEGORIES) as EvidenceCategoryId[]) {
    grouped[category] = {
      IMPLEMENTED: [],
      PLANNED: [],
      UNKNOWN: [],
    };
  }

  for (const fact of facts) {
    grouped[fact.category][fact.status].push(fact);
  }

  return grouped;
}
