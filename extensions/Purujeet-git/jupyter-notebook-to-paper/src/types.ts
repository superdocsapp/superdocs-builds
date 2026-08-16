export type EvidenceKind =
  | "metric"
  | "statistic"
  | "figure"
  | "table"
  | "equation"
  | "context";

export type PaperBlockType =
  | "heading"
  | "paragraph"
  | "figure"
  | "table"
  | "equation"
  | "conflict";

export interface SourceRef {
  notebook: string;
  cellId: string;
  cellIndex: number;
  sourceLineStart?: number;
  sourceLineEnd?: number;
  sourceCharStart?: number;
  sourceCharEnd?: number;
  outputIndex?: number;
  outputLineStart?: number;
  outputLineEnd?: number;
  outputCharStart?: number;
  outputCharEnd?: number;
}

export interface MetricConflict {
  key: string;
  label: string;
  evidenceIds: string[];
  values: unknown[];
  message: string;
}

export interface Evidence {
  id: string;
  kind: EvidenceKind;
  source: SourceRef;
  label: string;
  value?: unknown;
  unit?: string;
  fingerprint: string;
  metadata?: Record<string, unknown>;
}

export interface Claim {
  id: string;
  statement: string;
  evidenceIds: string[];
  metadata?: Record<string, unknown>;
}

export interface FigureArtifact {
  evidenceId: string;
  figureId: string;
  imageBase64: string;
  mimeType: string;
  hash: string;
  outputIndex?: number;
}

export interface PaperBlock {
  id: string;
  type: PaperBlockType;
  content: string;
  evidenceIds: string[];
  claimIds: string[];
  metadata?: Record<string, unknown>;
}

export interface PaperDocument {
  title: string;
  blocks: PaperBlock[];
  conflicts?: MetricConflict[];
}

export interface NotebookOutput {
  outputType: string;
  text?: string;
  html?: string;
  data?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  executionCount?: number | null;
}

export interface NotebookCell {
  id: string;
  index: number;
  cellType: "code" | "markdown" | "raw";
  source: string;
  outputs: NotebookOutput[];
  metadata: Record<string, unknown>;
}

export interface NotebookDocument {
  path: string;
  metadata: Record<string, unknown>;
  cells: NotebookCell[];
}

export interface EvidenceSnapshot {
  version: string;
  notebookPath: string;
  evidence: Evidence[];
  generatedAt: string;
}

export interface EvidenceChange {
  evidenceId: string;
  kind: "added" | "changed" | "removed";
  before?: Evidence;
  after?: Evidence;
}

export interface IncrementalDiff {
  changes: EvidenceChange[];
  affectedEvidenceIds: string[];
  affectedBlockIds: string[];
}
