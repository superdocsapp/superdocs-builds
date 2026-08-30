import type { Claim, DocumentType, Evidence, RiskCategory, SDDocument } from "../../../types/domain";
import { computeRisk } from "../../../domain/risk";
import type {
  ChangeImpactSummary,
  ContradictionFinding,
  ExtractedClaim,
  IntelligenceServices,
  ReviewRecommendation,
  SuggestedRequirement,
} from "../types";

const OBLIGATION_PATTERN = /\b(shall|will|must|guarantees?|commits? to|warrants?)\b/i;

const RISK_FACTOR_RATIONALE: Record<RiskCategory, string> = {
  "Unsupported Claim": "A claim with no supporting evidence, or evidence that fails to establish it, cannot be relied on in a decision.",
  "Conflicting Statement": "Two parts of the record disagree — resolve which one governs before relying on either.",
  "Stale Evidence": "The evidence on file has aged past its useful window and no longer reflects the current state of affairs.",
  "Missing Evidence": "A commitment exists in text with nothing on file to confirm it is actually being met.",
  "Rule Violation": "The document's own terms conflict with a policy it is supposed to satisfy.",
  "Unresolved Review": "A required review has not been completed, so the document's status is provisional.",
  "High-Impact Change": "A recent edit meaningfully shifted risk and has not yet been re-reviewed at the new terms.",
  "Incomplete Approval": "A required sign-off has not been recorded.",
};

function suggestedRequirementsFor(documentType: DocumentType): SuggestedRequirement[] {
  const common: SuggestedRequirement[] = [
    { category: "Metadata", description: "Document declares a version number and effective date", severity: "Low" },
    { category: "Approval", description: "A named approver has signed off before the document takes effect", severity: "Medium" },
  ];
  switch (documentType) {
    case "Vendor Agreement":
      return [
        ...common,
        { category: "Mandatory Section", description: "Data Security & Compliance section present", severity: "High" },
        { category: "Policy", description: "Breach notification window meets internal Incident Response Policy", severity: "High" },
        { category: "Citation", description: "Security and performance claims cite a named, dated source", severity: "Medium" },
      ];
    case "Security Assessment":
      return [
        ...common,
        { category: "Citation", description: "Every control claim cites an independently verifiable source", severity: "High" },
        { category: "Policy", description: "Meets the minimum security control policy for vendors with data access", severity: "High" },
      ];
    case "Policy":
      return [...common, { category: "Translation", description: "Non-English versions available for all offices the policy governs", severity: "Low" }];
    case "Compliance Letter":
      return [...common, { category: "Citation", description: "Any forward-looking date cites a firm, committed milestone", severity: "Medium" }];
    case "Legal Agreement":
    default:
      return [...common, { category: "Required Terminology", description: 'Contract defines "Confidential Information" with standard exclusions', severity: "Low" }];
  }
}

/**
 * Deterministic, in-memory implementations of the intelligence interfaces.
 * Every method still returns a Promise so call sites already look like
 * they're talking to a real, possibly-remote model — swapping the
 * implementation later is a one-line change at the call site.
 */
export const mockIntelligenceServices: IntelligenceServices = {
  claimExtraction: {
    async extractClaims(_documentId: string, _sectionId: string, sectionText: string): Promise<ExtractedClaim[]> {
      const sentences = sectionText.split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter(Boolean);
      return sentences.filter((s) => OBLIGATION_PATTERN.test(s)).map((text) => ({ text, claimant: "Extracted from section text" }));
    },
  },

  evidenceRetrieval: {
    async retrieveCandidateEvidence(claim: Claim, availableEvidence: Evidence[]): Promise<Evidence[]> {
      const claimWords = Array.from(new Set(claim.text.toLowerCase().split(/\W+/).filter((w) => w.length > 4)));
      if (claimWords.length === 0) return [];
      return availableEvidence
        .map((e) => {
          const haystack = `${e.title} ${e.description}`.toLowerCase();
          const score = claimWords.filter((w) => haystack.includes(w)).length;
          return { evidence: e, score };
        })
        .filter((x) => x.score > 0)
        .sort((a, b) => b.score - a.score)
        .map((x) => x.evidence);
    },
  },

  contradictionDetection: {
    async detectContradictions(claims: Claim[]): Promise<ContradictionFinding[]> {
      return claims
        .filter((c) => c.verificationStatus === "Contradicted")
        .map((c) => ({ claimId: c.id, explanation: c.contradictionNote ?? "Marked contradicted, but no explanation is on file." }));
    },
  },

  requirementExtraction: {
    async suggestRequirements(documentType: DocumentType): Promise<SuggestedRequirement[]> {
      return suggestedRequirementsFor(documentType);
    },
  },

  documentClassification: {
    async classify(rawText: string): Promise<DocumentType> {
      const text = rawText.toLowerCase();
      if (text.includes("master services agreement") || text.includes("subprocessor")) return "Vendor Agreement";
      if (text.includes("security questionnaire") || text.includes("self-attestation")) return "Security Assessment";
      if (text.includes("bridge letter") || text.includes("soc 2")) return "Compliance Letter";
      if (text.includes("confidential information") || text.includes("non-disclosure")) return "Legal Agreement";
      return "Policy";
    },
  },

  riskAnalysis: {
    async analyzeRisk(document: SDDocument) {
      return computeRisk(document);
    },
  },

  changeImpactAnalysis: {
    async analyzeChangeImpact(previous: SDDocument, next: SDDocument): Promise<ChangeImpactSummary> {
      const prevRisk = computeRisk(previous);
      const nextRisk = computeRisk(next);
      const changedClaims = next.claims.filter((c) => {
        const prior = previous.claims.find((p) => p.id === c.id);
        return !prior || prior.verificationStatus !== c.verificationStatus || prior.text !== c.text;
      });
      return {
        textChangeCount: changedClaims.length,
        riskDelta: nextRisk.openCount - prevRisk.openCount,
        highlights: changedClaims.map((c) => `Claim updated: "${c.text.slice(0, 72)}${c.text.length > 72 ? "…" : ""}"`),
      };
    },
  },

  reviewRecommendation: {
    async recommend(document: SDDocument): Promise<ReviewRecommendation[]> {
      const risk = computeRisk(document);
      const recommendations: ReviewRecommendation[] = risk.factors.slice(0, 4).map((factor) => ({
        id: `rec-factor-${factor.category.toLowerCase().replace(/\s+/g, "-")}`,
        title: `Address ${factor.label}`,
        rationale: RISK_FACTOR_RATIONALE[factor.category],
      }));

      const openHighPriorityActions = document.actions.filter((a) => a.status !== "Done" && a.priority === "High").slice(0, 3);
      for (const action of openHighPriorityActions) {
        if (recommendations.some((r) => r.relatedActionId === action.id)) continue;
        recommendations.push({
          id: `rec-action-${action.id}`,
          title: action.title,
          rationale: action.description,
          relatedActionId: action.id,
        });
      }

      return recommendations.slice(0, 6);
    },
  },
};
