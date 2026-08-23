/**
 * TaxOrganizer AI & SuperDocs Core Data Types
 */

export type ClientSegment = 'business' | 'rental' | 'expatriate' | 'individual' | 'hnw';

export interface TaxReturnData {
  taxYear: number;
  clientName: string;
  clientId: string;
  ssnEinLast4: string;
  segment: ClientSegment;
  filingStatus: string;
  income: {
    w2Wages?: number;
    businessNetProfit?: number; // Schedule C / K-1
    rentalNetIncome?: number; // Schedule E
    foreignEarnedIncome?: number; // Form 2555
    interestDividends?: number;
    capitalGains?: number;
  };
  schedulesApplied: string[]; // e.g. ['Schedule C', 'Schedule E', 'Form 2555', 'Schedule A']
  deductionsClaimed: {
    standardOrItemized: 'standard' | 'itemized';
    saltDeduction?: number;
    mortgageInterest?: number;
    charitableContributions?: number;
    section179Depreciation?: number;
    foreignTaxCredit?: number;
    qbiDeduction?: number;
    homeOfficeDeduction?: boolean;
    energyCredits?: number;
  };
  entitiesInvolved: string[]; // e.g. ["Acme Consulting LLC (1065 K-1)", "123 Maple St Property"]
  priorYearFormSources: {
    field: string;
    value: string | number;
    sourceLine: string; // e.g., "Form 1040, Line 1a" or "Schedule C, Line 31"
  }[];
  // The original uploaded filename, kept separate from clientName. clientName
  // is used in greetings/prose ("Dear ___,") and must never be a raw
  // filename -- a card can still show sourceFileName for traceability when
  // no real client name could be extracted, without that filename leaking
  // into client-facing letter text ("Dear extra.pdf," was a real bug).
  sourceFileName?: string;
  // Set when AI extraction did NOT complete cleanly (e.g. Gemini unreachable,
  // auth error, rate limit) and the record fell back to a generic organizer.
  // Surfaced in the UI so a generic card is honestly labeled as "AI extraction
  // unavailable" rather than looking like a weak-but-real extraction. Absent on
  // a successful extraction.
  extractionNotice?: {
    code: string;
    message: string;
  };
}

export interface TaxLawUpdate {
  id: string;
  title: string;
  codeSection: string;
  yearEffective: number;
  targetSegments: ClientSegment[];
  summary: string;
  impactExplanation: string;
  actionRequired: string;
}

export interface PreFilledOrganizerSection {
  id: string;
  sectionTitle: string;
  category: 'income' | 'deductions' | 'entities' | 'foreign' | 'general' | 'documents_needed';
  requiredDocuments: {
    id: string;
    docName: string;
    priorYearValue?: string;
    sourceCitation: string;
    status: 'received' | 'outstanding' | 'waived';
    receivedFileName?: string;
    receivedDate?: string;
  }[];
  questions: {
    id: string;
    questionText: string;
    priorYearAnswer: string;
    currentYearAnswer?: string;
    sourceCitation: string;
  }[];
}

export interface YearEndLetterContent {
  clientName: string;
  greeting: string;
  overview: string;
  personalizedLawParagraphs: {
    lawTitle: string;
    relevanceReason: string;
    estimatedImpact: string;
    actionItem: string;
  }[];
  filingDeadlineNotice: string;
  closing: string;
  // Approved diff edits merged into the letter at approval time. Every view
  // (preview, copy, print, export) reads this, so an approved edit shows up
  // consistently everywhere instead of only in the export. Empty until a diff
  // targeting the letter is approved.
  appliedEdits?: string[];
}

export interface SuperDocsDiff {
  id: string;
  targetSectionId: string;
  locationLabel: string;
  changeType: 'addition' | 'modification' | 'deletion';
  originalText: string;
  proposedText: string;
  explanation: string;
  citation: string;
  status: 'pending' | 'approved' | 'rejected';
  // Set when a live SuperDocs pending_changes entry could not be mapped to
  // proposed text (unknown/blank field shape). Lets the UI show an honest
  // "content could not be parsed" state instead of a silently empty diff.
  unmappable?: boolean;
}

export type AgentStage =
  | 'IDLE'
  | 'INGEST_PRIOR_RETURN'
  | 'CLASSIFY_SEGMENT'
  | 'MATCH_LAW_UPDATES'
  | 'GENERATE_DRAFT_BATCH'
  | 'SUPERDOCS_DIFF_GATE'
  | 'EXECUTE_APPROVALS'
  | 'TRACK_MISSING_ITEMS'
  | 'DRAFT_FOLLOWUP'
  | 'COMPLETED'
  | 'ERROR';

export interface StageLog {
  timestamp: string;
  stage: AgentStage;
  message: string;
  level: 'info' | 'warn' | 'error' | 'success';
  costDelta?: number;
  durationMs?: number;
}

export interface ClientBatchRecord {
  id: string;
  clientName: string;
  clientId: string;
  segment: ClientSegment;
  priorReturn: TaxReturnData;
  organizer: PreFilledOrganizerSection[];
  yearEndLetter: YearEndLetterContent;
  diffs: SuperDocsDiff[];
  missingItemsCount: number;
  receivedItemsCount: number;
  followUpLetterDraft?: string;
  status: 'draft' | 'diff_review' | 'ready_to_send' | 'client_returned' | 'completed';
  lastUpdated: string;
}

export interface BatchRunCheckpoint {
  runId: string;
  startTime: string;
  lastUpdatedTime: string;
  currentStage: AgentStage;
  completedStages: AgentStage[];
  logs: StageLog[];
  clientRecords: ClientBatchRecord[];
  totalCostEstimate: number;
  totalDurationMs: number;
  isPaused: boolean;
}

export interface SuperDocsEditInstructionRequest {
  documentId: string;
  instruction: string;
  currentDiffs: SuperDocsDiff[];
}
