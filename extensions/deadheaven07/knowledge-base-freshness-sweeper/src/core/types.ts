/**
 * Core Domain Models for Knowledge-base Freshness Sweeper
 * Task 2.3 — SuperDocs Extension
 */

export interface Screenshot {
  id: string;
  url: string;
  caption: string;
  ocr_labels: string[];
  surrounding_context?: string;
}

export interface Article {
  id: string;
  title: string;
  content: string;
  version: number;
  metadata: {
    category?: string;
    author?: string;
    tags?: string[];
    slug?: string;
    product_area?: string;
  };
  screenshots: Screenshot[];
  last_updated: string;
}

export type ChangeType =
  | 'RENAMED_SCREEN'
  | 'CHANGED_LIMIT'
  | 'RETIRED_PLAN'
  | 'CHANGED_WORKFLOW'
  | 'RELEASE_NOTES';

export interface ChangeEvent {
  id: string;
  type: ChangeType;
  title: string;
  description: string;
  before_state: {
    entity_name?: string;
    value?: string | number;
    path?: string;
    ui_label?: string;
    workflow_steps?: string[];
    details?: string;
  };
  after_state: {
    entity_name?: string;
    value?: string | number;
    path?: string;
    ui_label?: string;
    workflow_steps?: string[];
    details?: string;
  };
  effective_date: string;
  source: string;
}

export type AssessmentStatus = 'AFFECTED' | 'NOT_AFFECTED' | 'COULD_NOT_ASSESS';
export type ConfidenceLevel = 'HIGH' | 'MEDIUM' | 'LOW';

export interface EvidenceItem {
  sentence_index: number;
  sentence_text: string;
  section_heading?: string;
  matched_terms: string[];
  explanation: string;
  is_indirect: boolean;
  start_offset: number;
  end_offset: number;
}

export interface CouldNotAssessDetails {
  what_checked: string[];
  missing_evidence: string;
  why_insufficient: string;
}

export interface Assessment {
  article_id: string;
  change_id: string;
  status: AssessmentStatus;
  confidence: ConfidenceLevel;
  evidence: EvidenceItem[];
  affected_sections: string[];
  reason: string;
  could_not_assess_details?: CouldNotAssessDetails;
}

export interface ChangedSpan {
  start_char: number;
  end_char: number;
  original_text: string;
  replacement_text: string;
  sentence_index: number;
}

export type ProposalStatus = 'PENDING' | 'APPROVED' | 'REJECTED';

export interface EditProposal {
  id: string;
  article_id: string;
  change_id: string;
  original_content: string;
  proposed_content: string;
  changed_spans: ChangedSpan[];
  rationale: string;
  evidence: EvidenceItem[];
  confidence: ConfidenceLevel;
  status: ProposalStatus;
  created_at: string;
  reviewed_at?: string;
  reviewer?: string;
  review_notes?: string;
  structural_preservation_ratio: number;
}

export type ScreenshotStatus = 'SCREENSHOT_REPLACEMENT_REQUIRED' | 'SCREENSHOT_OK' | 'COULD_NOT_ASSESS';

export interface ScreenshotAssessment {
  article_id: string;
  screenshot_id: string;
  status: ScreenshotStatus;
  reason: string;
  evidence: string[];
  replacement_required: boolean;
  mismatched_labels: string[];
}

export interface ReviewDecision {
  proposal_id: string;
  decision: 'APPROVED' | 'REJECTED';
  reviewer: string;
  timestamp: string;
  notes?: string;
}

export interface PortfolioMetrics {
  total_articles: number;
  affected_articles: number;
  stale_articles: number;
  unchanged_articles: number;
  could_not_assess: number;
  freshness_score: number;
  assessment_coverage: number;
  precision: number;
  recall: number;
  f1_score: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  true_negatives: number;
  could_not_assess_rate: number;
  actual_cost: number;
  estimated_cost: number;
  budget_limit: number;
  model_calls: number;
}

export interface BudgetConfig {
  max_budget_usd: number;
  cost_per_1k_input_tokens: number;
  cost_per_1k_output_tokens: number;
}

export interface SweepOptions {
  sample_size?: number;
  budget_config?: Partial<BudgetConfig>;
  provider?: 'deterministic' | 'simulated-llm' | 'superdocs-mcp';
}

export interface GroundTruthEntry {
  article_id: string;
  expected_status: AssessmentStatus;
  expected_change_ids: string[];
  expected_affected_sentences: number[];
  expected_screenshot_replacement: boolean;
  category: string;
  rationale: string;
}
