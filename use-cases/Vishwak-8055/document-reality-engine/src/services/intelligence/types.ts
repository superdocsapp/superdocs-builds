import type { Claim, DocumentType, Evidence, Requirement, SDDocument } from "../../types/domain";
import type { RiskAssessment } from "../../domain/risk";

/**
 * These interfaces are the seam between SuperDocs and real intelligence.
 * Every implementation in `./mock` is deterministic and runs entirely on
 * the data already in the workspace — no network calls, no model. Swapping
 * in a real backend later means writing a new class that satisfies the same
 * interface; nothing in the UI layer needs to change because components
 * only ever depend on `IntelligenceServices`, never on the mock directly.
 */

export interface ExtractedClaim {
  text: string;
  claimant: string;
}
export interface ClaimExtractionService {
  extractClaims(documentId: string, sectionId: string, sectionText: string): Promise<ExtractedClaim[]>;
}

export interface EvidenceRetrievalService {
  /** Given a claim and everything already on file for its document, rank candidate evidence to link. */
  retrieveCandidateEvidence(claim: Claim, availableEvidence: Evidence[]): Promise<Evidence[]>;
}

export interface ContradictionFinding {
  claimId: string;
  explanation: string;
}
export interface ContradictionDetectionService {
  detectContradictions(claims: Claim[]): Promise<ContradictionFinding[]>;
}

export interface SuggestedRequirement {
  category: Requirement["category"];
  description: string;
  severity: Requirement["severity"];
}
export interface RequirementExtractionService {
  suggestRequirements(documentType: DocumentType): Promise<SuggestedRequirement[]>;
}

export interface DocumentClassificationService {
  classify(rawText: string): Promise<DocumentType>;
}

export interface RiskAnalysisService {
  analyzeRisk(document: SDDocument): Promise<RiskAssessment>;
}

export interface ChangeImpactSummary {
  textChangeCount: number;
  riskDelta: number;
  highlights: string[];
}
export interface ChangeImpactAnalysisService {
  analyzeChangeImpact(previous: SDDocument, next: SDDocument): Promise<ChangeImpactSummary>;
}

export interface ReviewRecommendation {
  id: string;
  title: string;
  rationale: string;
  relatedActionId?: string;
  relatedRiskId?: string;
}
export interface ReviewRecommendationService {
  recommend(document: SDDocument): Promise<ReviewRecommendation[]>;
}

export interface IntelligenceServices {
  claimExtraction: ClaimExtractionService;
  evidenceRetrieval: EvidenceRetrievalService;
  contradictionDetection: ContradictionDetectionService;
  requirementExtraction: RequirementExtractionService;
  documentClassification: DocumentClassificationService;
  riskAnalysis: RiskAnalysisService;
  changeImpactAnalysis: ChangeImpactAnalysisService;
  reviewRecommendation: ReviewRecommendationService;
}
