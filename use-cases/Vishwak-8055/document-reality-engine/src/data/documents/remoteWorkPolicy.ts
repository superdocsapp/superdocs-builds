import type { ActionItem, ChangeEvent, Claim, Decision, Evidence, ProvenanceRecord, Requirement, ReviewComment, ReviewEvent, Risk, SDDocument, Section } from "../../types/domain";

const DOC_ID = "doc-remote-work-policy";

const sections: Section[] = [
  {
    id: "sec-rw-1",
    documentId: DOC_ID,
    order: 1,
    heading: "1. Eligibility & Work Arrangements",
    body: `This policy applies to all full-time employees whose role has been designated as remote-eligible by their manager and People Operations. Remote-eligible employees may work from any location within their home country without prior approval. Employees seeking to work temporarily from a different country must submit a Cross-Border Work Request at least three (3) weeks in advance.`,
    claimIds: [],
  },
  {
    id: "sec-rw-2",
    documentId: DOC_ID,
    order: 2,
    heading: "2. Equipment & Security Requirements",
    body: `All remote employees must use company-managed devices configured with full-disk encryption, endpoint detection and response (EDR) software, and automatic security patching. Personal devices may not be used to access production systems or customer data under any circumstances.`,
    claimIds: ["claim-rw-02"],
  },
  {
    id: "sec-rw-3",
    documentId: DOC_ID,
    order: 3,
    heading: "3. Tax & Compliance Considerations",
    body: `Employees working remotely from a country other than their home country for more than thirty (30) consecutive days must notify People Operations for a tax and immigration compliance review. Remote work arrangements do not affect an employee's eligibility for overtime pay under applicable local law.`,
    claimIds: ["claim-rw-01", "claim-rw-03"],
  },
];

const claims: Claim[] = [
  {
    id: "claim-rw-01",
    documentId: DOC_ID,
    sectionId: "sec-rw-3",
    text: "Employees working remotely from a country other than their home country for more than 30 days must notify People Operations for a tax/compliance review.",
    claimant: "People Operations",
    evidenceIds: ["ev-rw-01"],
    verificationStatus: "Verified",
    confidence: 90,
    lastVerifiedAt: "2025-11-10T00:00:00.000Z",
    reviewer: "Lena Forsythe",
  },
  {
    id: "claim-rw-02",
    documentId: DOC_ID,
    sectionId: "sec-rw-2",
    text: "All remote employees must use company-managed devices with full-disk encryption and endpoint detection software.",
    claimant: "People Operations",
    evidenceIds: ["ev-rw-02"],
    verificationStatus: "Verified",
    confidence: 94,
    lastVerifiedAt: "2026-06-15T09:00:00.000Z",
    reviewer: "Tomas Novak",
  },
  {
    id: "claim-rw-03",
    documentId: DOC_ID,
    sectionId: "sec-rw-3",
    text: "Remote work arrangements do not affect an employee's eligibility for overtime pay under applicable local law.",
    claimant: "People Operations",
    evidenceIds: [],
    verificationStatus: "Needs Review",
    confidence: 55,
  },
];

const evidence: Evidence[] = [
  {
    id: "ev-rw-01",
    documentId: DOC_ID,
    title: "Global Mobility Policy Cross-Reference",
    description: "Cross-references the 30-day threshold and notification requirement used by the Global Mobility team.",
    sourceType: "Policy Document",
    sourceName: "Global Mobility Policy v4",
    reference: "GMP-4",
    strength: "Strong",
    collectedAt: "2025-10-15T00:00:00.000Z",
    linkedClaimIds: ["claim-rw-01"],
  },
  {
    id: "ev-rw-02",
    documentId: DOC_ID,
    title: "IT Asset Management Standard",
    description: "Specifies full-disk encryption and EDR as baseline requirements for all managed endpoints.",
    sourceType: "Policy Document",
    sourceName: "IT Asset Management Standard v3",
    reference: "ITAM-3",
    strength: "Strong",
    collectedAt: "2025-10-20T00:00:00.000Z",
    linkedClaimIds: ["claim-rw-02"],
  },
];

const requirements: Requirement[] = [
  {
    id: "req-rw-01",
    documentId: DOC_ID,
    category: "Mandatory Section",
    description: "Equipment & Security Requirements section present",
    status: "Satisfied",
    explanation: "Section 2 covers device management, encryption, and EDR requirements.",
    relatedSectionId: "sec-rw-2",
    severity: "Low",
  },
  {
    id: "req-rw-02",
    documentId: DOC_ID,
    category: "Metadata",
    description: "Document declares a version number and effective date",
    status: "Satisfied",
    explanation: "Tracked as v2.1, effective December 1, 2025.",
    severity: "Low",
  },
  {
    id: "req-rw-03",
    documentId: DOC_ID,
    category: "Policy",
    description: "Aligned with the Global Mobility Policy's cross-border thresholds",
    status: "Satisfied",
    explanation: "The 30-day notification threshold matches the Global Mobility Policy exactly.",
    severity: "Low",
  },
  {
    id: "req-rw-04",
    documentId: DOC_ID,
    category: "Translation",
    description: "Non-English versions available for all offices",
    status: "Warning",
    explanation: "Spanish and German translations are complete; the Japanese translation for the Tokyo office is still in progress.",
    severity: "Low",
  },
  {
    id: "req-rw-05",
    documentId: DOC_ID,
    category: "Approval",
    description: "HR leadership sign-off required before publication",
    status: "Satisfied",
    explanation: "Approved by Priya Nandakumar (Legal) on behalf of HR leadership on November 25, 2025.",
    severity: "Medium",
  },
];

const risks: Risk[] = [
  {
    id: "risk-rw-01",
    documentId: DOC_ID,
    category: "Rule Violation",
    title: "Translation gap could create inconsistent application in the Tokyo office",
    description: "Without a Japanese translation, the Tokyo office relies on informal summaries of the policy rather than the controlling text.",
    severity: "Low",
    status: "Open",
    detectedAt: "2026-06-01T00:00:00.000Z",
    relatedClaimIds: [],
    relatedRequirementIds: ["req-rw-04"],
    relatedEvidenceIds: [],
  },
];

const decisions: Decision[] = [
  {
    id: "dec-rw-01",
    documentId: DOC_ID,
    description: "Approve v2.1 for global rollout",
    outcome: "Approved",
    decidedBy: "Lena Forsythe",
    decidedAt: "2026-06-15T10:00:00.000Z",
    relatedReviewEventId: "rev-rw-06",
    notes: "Clarifications to the cross-border request timeline and EDR requirement approved without further review.",
  },
];

const actions: ActionItem[] = [
  {
    id: "act-rw-01",
    documentId: DOC_ID,
    title: "Complete the Japanese translation for the Tokyo office",
    description: "Finalize and publish the Japanese-language version of the policy.",
    assignee: "Lena Forsythe",
    status: "Open",
    priority: "Medium",
    dueDate: "2026-09-30",
    relatedRequirementId: "req-rw-04",
  },
];

const changes: ChangeEvent[] = [
  {
    id: "change-rw-01",
    documentId: DOC_ID,
    fromVersion: "2.0",
    toVersion: "2.1",
    occurredAt: "2026-06-15T09:30:00.000Z",
    author: "Lena Forsythe",
    summary: "Clarified the cross-border work request timeline and added an explicit EDR requirement.",
    textChangeCount: 5,
    claimChangeIds: ["claim-rw-02"],
    requirementChangeIds: [],
    evidenceChangeIds: ["ev-rw-02"],
    riskDelta: 0,
    highlights: [
      "Clarified that a Cross-Border Work Request must be submitted 3 weeks in advance (previously unspecified)",
      "Added an explicit EDR requirement alongside full-disk encryption",
    ],
  },
];

const reviewEvents: ReviewEvent[] = [
  {
    id: "rev-rw-01",
    documentId: DOC_ID,
    timestamp: "2025-11-01T09:00:00.000Z",
    actor: "Lena Forsythe",
    type: "Document Created",
    affectedType: "Document",
    affectedId: DOC_ID,
    explanation: "Drafted to formalize remote-work practices adopted informally since 2023.",
  },
  {
    id: "rev-rw-02",
    documentId: DOC_ID,
    timestamp: "2025-11-05T10:00:00.000Z",
    actor: "Lena Forsythe",
    type: "Evidence Attached",
    affectedType: "Evidence",
    affectedId: "ev-rw-01",
    explanation: "Cross-referenced the Global Mobility Policy's 30-day threshold.",
  },
  {
    id: "rev-rw-03",
    documentId: DOC_ID,
    timestamp: "2025-11-06T11:00:00.000Z",
    actor: "Tomas Novak",
    type: "Evidence Attached",
    affectedType: "Evidence",
    affectedId: "ev-rw-02",
    explanation: "Attached the IT Asset Management Standard supporting the device-security claim.",
  },
  {
    id: "rev-rw-04",
    documentId: DOC_ID,
    timestamp: "2025-11-20T09:00:00.000Z",
    actor: "Lena Forsythe",
    type: "Approval Requested",
    affectedType: "Document",
    affectedId: DOC_ID,
    explanation: "Requested HR leadership sign-off ahead of the December 1 effective date.",
  },
  {
    id: "rev-rw-05",
    documentId: DOC_ID,
    timestamp: "2025-11-25T14:00:00.000Z",
    actor: "Priya Nandakumar",
    type: "Approval Granted",
    affectedType: "Document",
    affectedId: DOC_ID,
    explanation: "Approved on behalf of HR leadership; published December 1, 2025.",
  },
  {
    id: "rev-rw-06",
    documentId: DOC_ID,
    timestamp: "2026-06-15T09:30:00.000Z",
    actor: "Lena Forsythe",
    type: "Content Changed",
    affectedType: "Document",
    affectedId: DOC_ID,
    explanation: "Published v2.1 with the cross-border timeline clarification and EDR requirement.",
  },
];

const comments: ReviewComment[] = [
  {
    id: "comment-rw-01",
    documentId: DOC_ID,
    targetType: "Requirement",
    targetId: "req-rw-04",
    author: "Lena Forsythe",
    text: "Translation vendor confirmed the Japanese draft will be ready by end of Q3.",
    createdAt: "2026-06-20T00:00:00.000Z",
  },
];

const provenance: ProvenanceRecord[] = [
  {
    id: "prov-rw-01",
    subjectType: "Evidence",
    subjectId: "ev-rw-01",
    origin: "Internal review",
    occurredAt: "2025-11-05T10:00:00.000Z",
    actor: "Lena Forsythe",
    transformation: "Cross-checked against the Global Mobility Policy during drafting.",
  },
  {
    id: "prov-rw-02",
    subjectType: "Evidence",
    subjectId: "ev-rw-02",
    origin: "Internal review",
    occurredAt: "2025-11-06T11:00:00.000Z",
    actor: "Tomas Novak",
    transformation: "Confirmed against the current IT Asset Management Standard.",
  },
];

export const remoteWorkPolicy: SDDocument = {
  id: DOC_ID,
  title: "Remote Work Policy — Global v2",
  type: "Policy",
  version: "2.1",
  status: "Published",
  owner: { name: "Lena Forsythe", role: "Director, People Operations" },
  createdAt: "2025-11-01T09:00:00.000Z",
  updatedAt: "2026-06-15T10:00:00.000Z",
  effectiveDate: "2025-12-01",
  sections,
  claims,
  requirements,
  evidence,
  risks,
  decisions,
  actions,
  changes,
  reviewEvents,
  comments,
  provenance,
};
