export type SupplierTier = "TIER_1_STRATEGIC" | "TIER_2_MANUFACTURING" | "TIER_3_COMMODITY";
export type Region = "EU" | "NORTH_AMERICA" | "APAC" | "GLOBAL";
export type AttestationStatus = 
  | "DRAFT" 
  | "ISSUED" 
  | "SUBMITTED" 
  | "NORMALIZED" 
  | "UNDER_REVIEW" 
  | "APPROVED" 
  | "FOLLOW_UP_REQUIRED" 
  | "CLOSED";

export type ESGPillar = "ENVIRONMENTAL" | "SOCIAL" | "GOVERNANCE";
export type FindingSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "OBSERVATION";
export type ReviewDecision = "PENDING" | "ACCEPTED" | "REJECTED";
export type RiskTier = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type LetterStatus = "DRAFT" | "APPROVED" | "SENT";

export interface Supplier {
  id: string;
  name: string;
  code: string;
  tier: SupplierTier;
  region: Region;
  country: string;
  primary_contact_email: string;
  created_at: string;
  updated_at: string;
}

export interface AttestationCycle {
  id: string;
  supplier_id: string;
  cycle_year: number;
  status: AttestationStatus;
  issued_document_id?: string;
  issued_document_url?: string;
  response_document_id?: string;
  response_document_name?: string;
  response_format?: string;
  submitted_at?: string;
  normalized_at?: string;
  created_at: string;
  updated_at: string;
}

export interface Finding {
  id: string;
  pillar: ESGPillar;
  severity: FindingSeverity;
  standard_clause: string;
  shortfall_summary: string;
  supplier_exact_quote: string;
  source_location?: string;
  recommended_action: string;
  review_decision: ReviewDecision;
  review_notes?: string;
}

export interface Assessment {
  id: string;
  attestation_id: string;
  overall_risk_score: number;
  risk_tier: RiskTier;
  environmental_score: number;
  social_score: number;
  governance_score: number;
  summary_markdown?: string;
  is_approved: boolean;
  approved_by?: string;
  approved_at?: string;
  findings: Finding[];
  created_at: string;
  updated_at: string;
}

export interface FollowUpLetter {
  id: string;
  attestation_id: string;
  recipient_email: string;
  subject: string;
  content_markdown: string;
  superdocs_doc_id?: string;
  superdocs_export_url?: string;
  status: LetterStatus;
  created_at: string;
  updated_at: string;
}

export interface RiskDistributionItem {
  category: string;
  count: number;
  percentage: number;
}

export interface PillarAverageScores {
  environmental_avg: number;
  social_avg: number;
  governance_avg: number;
  overall_compliance_avg: number;
}

export interface TierRiskData {
  tier: SupplierTier;
  total_suppliers: number;
  low_risk: number;
  medium_risk: number;
  high_risk: number;
  critical_risk: number;
}

export interface RegionalRiskData {
  region: Region;
  total_suppliers: number;
  low_risk: number;
  medium_risk: number;
  high_risk: number;
}

export interface TopFindingShortfall {
  standard_clause: string;
  pillar: string;
  occurrence_count: number;
  severity: string;
}

export interface ProgrammeReport {
  cycle_year: number;
  total_suppliers_invited: number;
  responses_submitted: number;
  attestation_rate_pct: number;
  overall_programme_risk_level: string;
  pillar_averages: PillarAverageScores;
  risk_tier_breakdown: RiskDistributionItem[];
  tier_distribution: TierRiskData[];
  regional_distribution: RegionalRiskData[];
  top_recurring_shortfalls: TopFindingShortfall[];
  executive_narrative_markdown: string;
  generated_at: string;
}
