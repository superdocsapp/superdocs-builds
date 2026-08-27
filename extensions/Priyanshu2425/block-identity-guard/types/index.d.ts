/**
 * Type definitions for superdocs-block-identity-guard.
 *
 * Hand-written rather than generated: the package ships as plain ES modules with
 * no build step, so these are the only contract a TypeScript consumer sees, and
 * they are kept deliberately narrow.
 */

export type Severity = 'error' | 'warning' | 'info' | 'notice';
export type Confidence = 'high' | 'medium' | 'low';

export type RuleCode =
  | 'IDS_REGENERATED'
  | 'ALL_IDS_STRIPPED'
  | 'LOST_ATTRIBUTE_STRIPPED'
  | 'LOST_NODE_REBUILT'
  | 'LOST_MARKDOWN_HOP'
  | 'LOST_BLOCK_REMOVED'
  | 'LOST_SUBTREE'
  | 'DUPLICATE_ID'
  | 'DUPLICATE_ID_IN_SOURCE'
  | 'DATA_ATTRIBUTE_DROPPED'
  | 'PART_OMITTED'
  | 'BLOCK_MOVED'
  | 'CONTENT_CHANGED'
  | 'NEW_IDS'
  | 'NO_IDS_IN_SOURCE';

export interface Locator {
  /** The identifier this block carried in the before document. */
  id: string;
  tag: string;
  /** Position among identified blocks in the before document, 1-based. */
  blockIndex: number;
  /** Structural path, e.g. `div > section[2] > p[7]`. */
  path: string;
  /** First sixty characters of the block's normalised text. */
  preview: string;
  line: number;
  column: number;
  /** Nearest ancestor block that carries an identifier, or null. */
  parentId: string | null;
  /** `header`, `footer`, `footnote`, `comment`, or null for body content. */
  partType: string | null;
}

export interface Counterpart {
  tag: string;
  line: number;
  column: number;
  preview: string;
  attributes: string[];
  hasIdAttribute: boolean;
}

export interface FindingMember {
  id: string;
  rule?: RuleCode;
  cause?: string;
  confidence?: Confidence;
  locator: Locator;
  counterpart: Counterpart | null;
}

export interface Finding {
  rule: RuleCode;
  severity: Severity;
  title: string;
  meaning: string;
  /** The block's identifier, or the ancestor's when `idRole` is `anchor`. */
  id: string | null;
  idRole: 'block' | 'anchor';
  /** The transformation this finding names, in a sentence. */
  cause: string;
  confidence: Confidence;
  evidence: string[];
  locator: Locator | null;
  counterpart: Counterpart | null;
  members: FindingMember[];
  /** Stable across runs; what a baseline file records. */
  key: string;
  baselined?: boolean;
}

export interface ReportCounts {
  beforeBlocks: number;
  afterBlocks: number;
  intact: number;
  lost: number;
  duplicated: number;
  moved: number;
  added: number;
  partsOmitted: number;
}

export interface Report {
  schemaVersion: number;
  idAttribute: string;
  /** True when nothing at `error` severity survived. */
  ok: boolean;
  counts: ReportCounts;
  summary: Record<Severity, number>;
  findings: Finding[];
  signals: { beforeIdCount: number; afterIdCount: number; lostTags: string[] };
  baselined?: Finding[];
  baselineApplied?: { accepted: number; matched: number; stale: number };
}

export interface CheckOptions {
  /** Default `data-chunk-id`. */
  idAttribute?: string;
  /** Treat an omitted header/footer/footnote/comment as a failure. Default false. */
  strictParts?: boolean;
  /** Also report blocks that kept their identifier and changed text. Default false. */
  includeContentChanges?: boolean;
  /** Refuse inputs larger than this many characters. Default 25 MB. */
  maxBytes?: number;
}

export interface AssertOptions extends CheckOptions {
  /** Severity that throws. Default `error`. */
  failOn?: Severity | 'never';
}

export interface FormatOptions {
  format?: 'human' | 'json' | 'github';
  colour?: boolean;
  /** File path to attribute findings to, for the `github` format. */
  file?: string;
  compact?: boolean;
}

export interface Baseline {
  baselineVersion: number;
  idAttribute?: string;
  note?: string;
  accepted: Array<{ key: string; rule?: RuleCode; id?: string | null; where?: string | null; text?: string | null }>;
}

export interface CaptureOptions {
  /** Pick one document out of a multi-document session. */
  documentId?: string;
  /** Event to read. Default `document_sync`. */
  event?: string;
}

export interface CaptureResult {
  html: string;
  source: string;
  documentId: string | null;
  candidates: number;
}

export declare class RoundTripError extends Error {
  readonly name: 'RoundTripError';
  readonly report: Report;
}

export declare function checkRoundTrip(
  beforeHtml: string,
  afterHtml: string,
  options?: CheckOptions,
): Report;

export declare function assertRoundTrip(
  beforeHtml: string,
  afterHtml: string,
  options?: AssertOptions,
): Report;

export declare function hasFindingsAtLeast(report: Report, threshold?: Severity | 'never'): boolean;
export declare function formatReport(report: Report, options?: FormatOptions): string;
export declare function createBaseline(report: Report, options?: { note?: string }): Baseline;
export declare function applyBaseline(report: Report, baseline: Baseline | null): Report;
export declare function extractDocumentHtml(payload: string, options?: CaptureOptions): CaptureResult;

export declare const RULES: Record<RuleCode, { code: RuleCode; severity: Severity; title: string; meaning: string }>;
export declare const SEVERITIES: Severity[];
export declare const SCHEMA_VERSION: number;
export declare function severityRank(severity: Severity): number;
export declare function atLeastAsSevere(severity: Severity, threshold: Severity): boolean;
export declare function analyse(beforeHtml: string, afterHtml: string, options?: CheckOptions): Report;
