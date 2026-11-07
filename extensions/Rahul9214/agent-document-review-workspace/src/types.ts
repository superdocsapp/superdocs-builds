export type ReviewStatus = 'pending' | 'approved' | 'rejected' | 'applied' | 'reverted';
export type VerificationStatus = 'verified' | 'mismatch';

export interface ChangeItem {
  id: string;
  documentId: string;
  agent: string;
  turn: number;
  section: string;
  before: string;
  after: string;
  claim: string;
  actual: string;
  verification: VerificationStatus;
  status: ReviewStatus;
  artifactState: string;
}

export interface DocumentRecord {
  id: string;
  name: string;
  kind: 'docx';
  owner: string;
}

export interface WorkspaceState {
  documents: DocumentRecord[];
  changes: ChangeItem[];
  selectedChangeId: string;
}
