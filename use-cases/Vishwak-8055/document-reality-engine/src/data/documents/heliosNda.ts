import type { ActionItem, ChangeEvent, Claim, Decision, Evidence, ProvenanceRecord, Requirement, ReviewEvent, SDDocument, Section } from "../../types/domain";

const DOC_ID = "doc-helios-nda";

const sections: Section[] = [
  {
    id: "sec-hv-1",
    documentId: DOC_ID,
    order: 1,
    heading: "1. Confidential Information & Exclusions",
    body: `"Confidential Information" means any non-public information disclosed by either party, whether orally or in writing, that is designated as confidential or that a reasonable person would understand to be confidential given the nature of the information. Confidential Information does not include information that: (a) is or becomes publicly available through no fault of the receiving party; (b) was rightfully known to the receiving party prior to disclosure; or (c) is independently developed without use of the disclosing party's Confidential Information, including residual knowledge retained in the unaided memory of individuals who had access to it.`,
    claimIds: ["claim-hv-02"],
  },
  {
    id: "sec-hv-2",
    documentId: DOC_ID,
    order: 2,
    heading: "2. Term & Survival",
    body: `This Agreement remains in effect for two (2) years from the Effective Date. Confidentiality obligations with respect to any Confidential Information disclosed during the term survive for three (3) years following disclosure. Neither party may issue a press release or public statement referencing the existence or terms of the parties' discussions without the other party's prior written consent.`,
    claimIds: ["claim-hv-01", "claim-hv-03"],
  },
];

const claims: Claim[] = [
  {
    id: "claim-hv-01",
    documentId: DOC_ID,
    sectionId: "sec-hv-2",
    text: "Confidentiality obligations survive termination for a period of three (3) years.",
    claimant: "Solstice Robotics, Inc. / Helios Ventures LLC",
    evidenceIds: ["ev-hv-01"],
    verificationStatus: "Verified",
    confidence: 96,
    lastVerifiedAt: "2026-07-02T10:00:00.000Z",
    reviewer: "Ravi Subramaniam",
  },
  {
    id: "claim-hv-02",
    documentId: DOC_ID,
    sectionId: "sec-hv-1",
    text: "Residual knowledge retained in employees' unaided memory is excluded from confidentiality obligations.",
    claimant: "Solstice Robotics, Inc. / Helios Ventures LLC",
    evidenceIds: ["ev-hv-02"],
    verificationStatus: "Verified",
    confidence: 93,
    lastVerifiedAt: "2026-07-02T10:05:00.000Z",
    reviewer: "Ravi Subramaniam",
  },
  {
    id: "claim-hv-03",
    documentId: DOC_ID,
    sectionId: "sec-hv-2",
    text: "Neither party may issue a press release referencing the other without prior written consent.",
    claimant: "Solstice Robotics, Inc. / Helios Ventures LLC",
    evidenceIds: ["ev-hv-03"],
    verificationStatus: "Verified",
    confidence: 95,
    lastVerifiedAt: "2026-07-02T10:10:00.000Z",
    reviewer: "Ravi Subramaniam",
  },
];

const evidence: Evidence[] = [
  {
    id: "ev-hv-01",
    documentId: DOC_ID,
    title: "Term & Survival Clause, §2",
    description: "States the 3-year survival period directly.",
    sourceType: "Contract Clause",
    sourceName: "NDA §2",
    reference: "HV-NDA-2",
    strength: "Strong",
    collectedAt: "2026-07-01T00:00:00.000Z",
    linkedClaimIds: ["claim-hv-01"],
  },
  {
    id: "ev-hv-02",
    documentId: DOC_ID,
    title: "Confidential Information Definition, §1(c)",
    description: "Explicitly excludes residual, unaided-memory knowledge from the definition.",
    sourceType: "Contract Clause",
    sourceName: "NDA §1(c)",
    reference: "HV-NDA-1C",
    strength: "Strong",
    collectedAt: "2026-07-01T00:00:00.000Z",
    linkedClaimIds: ["claim-hv-02"],
  },
  {
    id: "ev-hv-03",
    documentId: DOC_ID,
    title: "Publicity Clause, §2",
    description: "Requires prior written consent before either party references the relationship publicly.",
    sourceType: "Contract Clause",
    sourceName: "NDA §2",
    reference: "HV-NDA-2",
    strength: "Strong",
    collectedAt: "2026-07-01T00:00:00.000Z",
    linkedClaimIds: ["claim-hv-03"],
  },
];

const requirements: Requirement[] = [
  {
    id: "req-hv-01",
    documentId: DOC_ID,
    category: "Mandatory Section",
    description: "Term & Survival section present",
    status: "Satisfied",
    explanation: "Section 2 states the term, survival period, and publicity restriction.",
    relatedSectionId: "sec-hv-2",
    severity: "Low",
  },
  {
    id: "req-hv-02",
    documentId: DOC_ID,
    category: "Required Terminology",
    description: '"Confidential Information" is defined with the standard exclusions',
    status: "Satisfied",
    explanation: "Section 1 matches the Legal Playbook's model definition, including all three standard exclusions.",
    severity: "Low",
  },
  {
    id: "req-hv-03",
    documentId: DOC_ID,
    category: "Metadata",
    description: "Document declares a version number and effective date",
    status: "Satisfied",
    explanation: "Tracked as v1.1, effective July 5, 2026.",
    severity: "Low",
  },
  {
    id: "req-hv-04",
    documentId: DOC_ID,
    category: "Approval",
    description: "Corporate Counsel sign-off required before execution",
    status: "Satisfied",
    explanation: "Approved by Ravi Subramaniam on July 3, 2026.",
    severity: "Medium",
  },
];

const decisions: Decision[] = [
  {
    id: "dec-hv-01",
    documentId: DOC_ID,
    description: "Approve NDA for execution",
    outcome: "Approved",
    decidedBy: "Ravi Subramaniam",
    decidedAt: "2026-07-03T10:00:00.000Z",
    relatedReviewEventId: "rev-hv-04",
    notes: "Standard mutual NDA terms; all claims verified directly against clause text.",
  },
];

const actions: ActionItem[] = [
  {
    id: "act-hv-01",
    documentId: DOC_ID,
    title: "File signed NDA in the contract repository",
    description: "Upload the countersigned copy and tag it against the Helios Ventures partnership record.",
    assignee: "Ravi Subramaniam",
    status: "Done",
    priority: "Low",
    dueDate: "2026-07-10",
  },
];

const changes: ChangeEvent[] = [
  {
    id: "change-hv-01",
    documentId: DOC_ID,
    fromVersion: "1.0",
    toVersion: "1.1",
    occurredAt: "2026-07-20T14:00:00.000Z",
    author: "Ravi Subramaniam",
    summary: "Updated the notice address after Helios changed offices; no substantive terms changed.",
    textChangeCount: 2,
    claimChangeIds: [],
    requirementChangeIds: [],
    evidenceChangeIds: [],
    riskDelta: 0,
    highlights: ["Updated Helios Ventures' notice address to its new San Mateo office"],
  },
];

const reviewEvents: ReviewEvent[] = [
  {
    id: "rev-hv-01",
    documentId: DOC_ID,
    timestamp: "2026-07-01T09:00:00.000Z",
    actor: "Ravi Subramaniam",
    type: "Document Created",
    affectedType: "Document",
    affectedId: DOC_ID,
    explanation: "Drafted from the standard mutual NDA template ahead of partnership discussions with Helios Ventures.",
  },
  {
    id: "rev-hv-02",
    documentId: DOC_ID,
    timestamp: "2026-07-02T10:00:00.000Z",
    actor: "Ravi Subramaniam",
    type: "Claim Verified",
    affectedType: "Claim",
    affectedId: "claim-hv-01",
    explanation: "Verified the 3-year survival period directly against Section 2.",
  },
  {
    id: "rev-hv-03",
    documentId: DOC_ID,
    timestamp: "2026-07-03T09:00:00.000Z",
    actor: "Ravi Subramaniam",
    type: "Approval Requested",
    affectedType: "Document",
    affectedId: DOC_ID,
    explanation: "Requested sign-off ahead of the planned July 5 effective date.",
  },
  {
    id: "rev-hv-04",
    documentId: DOC_ID,
    timestamp: "2026-07-03T10:00:00.000Z",
    actor: "Ravi Subramaniam",
    type: "Approval Granted",
    affectedType: "Document",
    affectedId: DOC_ID,
    explanation: "Standard mutual NDA terms with no deviations; approved for execution.",
  },
  {
    id: "rev-hv-05",
    documentId: DOC_ID,
    timestamp: "2026-07-20T14:00:00.000Z",
    actor: "Ravi Subramaniam",
    type: "Content Changed",
    affectedType: "Document",
    affectedId: DOC_ID,
    explanation: "Updated the notice address after Helios relocated; no substantive terms changed.",
  },
];

const provenance: ProvenanceRecord[] = [
  {
    id: "prov-hv-01",
    subjectType: "Claim",
    subjectId: "claim-hv-01",
    origin: "Internal review",
    occurredAt: "2026-07-02T10:00:00.000Z",
    actor: "Ravi Subramaniam",
    transformation: "Cross-checked against the Legal Playbook's standard NDA survival term.",
  },
];

export const heliosNda: SDDocument = {
  id: DOC_ID,
  title: "Mutual NDA — Helios Ventures Partnership",
  type: "Legal Agreement",
  version: "1.1",
  status: "Approved",
  owner: { name: "Ravi Subramaniam", role: "Corporate Counsel" },
  counterparty: "Helios Ventures LLC",
  createdAt: "2026-07-01T09:00:00.000Z",
  updatedAt: "2026-07-20T14:00:00.000Z",
  effectiveDate: "2026-07-05",
  sections,
  claims,
  requirements,
  evidence,
  risks: [],
  decisions,
  actions,
  changes,
  reviewEvents,
  comments: [],
  provenance,
};
