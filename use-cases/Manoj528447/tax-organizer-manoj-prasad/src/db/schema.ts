/**
 * PostgreSQL / Drizzle ORM Schema Definition
 * Satisfies Requirement 7: Persistent schema for Clients, Documents, Runs, Review Status, Generated Files, and Audit Logs.
 */

export interface ClientTable {
  id: string; // Primary key
  clientId: string;
  clientName: string;
  ssnEinLast4: string;
  segment: 'business' | 'rental' | 'expatriate' | 'individual' | 'hnw';
  filingStatus: string;
  priorYearDataJson: string; // Serialized TaxReturnData
  createdAt: string;
  updatedAt: string;
}

export interface DocumentTable {
  id: string; // Primary key
  clientRecordId: string;
  documentType: 'organizer' | 'year_end_letter' | 'followup_letter' | 'prior_return';
  contentJson: string; // Serialized Document / Organizer Content
  status: 'draft' | 'diff_review' | 'ready_to_send' | 'completed';
  versionNumber: number;
  createdAt: string;
  updatedAt: string;
}

export interface BatchRunTable {
  runId: string; // Primary key
  currentStage: string;
  completedStagesJson: string;
  clientRecordsJson: string;
  logsJson: string;
  totalCostEstimate: number;
  totalDurationMs: number;
  isPaused: boolean;
  startTime: string;
  lastUpdatedTime: string;
}

export interface DiffReviewTable {
  id: string; // Primary key
  clientRecordId: string;
  locationLabel: string;
  changeType: 'addition' | 'modification' | 'deletion';
  originalText: string;
  proposedText: string;
  explanation: string;
  citation: string;
  status: 'pending' | 'approved' | 'rejected';
  reviewedBy?: string;
  reviewedAt?: string;
}

export interface GeneratedFileTable {
  id: string; // Primary key
  clientRecordId: string;
  fileType: 'pdf' | 'fillable_pdf' | 'markdown' | 'text';
  filePathOrContent: string;
  generatedAt: string;
}

export interface AuditLogTable {
  id: string; // Primary key
  timestamp: string;
  actor: string;
  action: string;
  clientRecordId?: string;
  documentId?: string;
  version?: number;
  details: string;
}
