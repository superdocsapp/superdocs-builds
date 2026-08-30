/**
 * Core domain types for the Translation-Ready Manuscript use case.
 *
 * One rule governs this whole file: information has a provenance, and its
 * provenance determines its authority.
 *
 *   EXTRACTED  -> read straight off the document by the parser. Not a guess.
 *   SUGGESTED  -> required interpretation (an LLM call). Carries evidence
 *                 and a confidence. Not enforceable until reviewed.
 *   CONFIRMED  -> a human looked at a SUGGESTED item and approved it
 *                 (verbatim or edited). Only CONFIRMED rules are enforced
 *                 as hard mismatches during translation QA.
 *   REJECTED   -> a human looked at a SUGGESTED item and declined it. Kept
 *                 on record (not deleted) so a later pass can't silently
 *                 resurrect it.
 *
 * Nothing gets promoted from SUGGESTED to CONFIRMED automatically. There is
 * no "confirmed by default" path anywhere in this codebase -- see
 * rules/protectedTerms.ts for where that's enforced in code, not just here
 * in the type.
 */
export type ProvenanceStatus = "extracted" | "suggested" | "confirmed" | "rejected";

/** Where a piece of information came from, down to the paragraph. */
export interface SourceLocation {
  chapterId: string;
  chapterTitle: string;
  /** Index of the block (paragraph/verse/dialogue line) within the chapter, 0-based. */
  blockIndex: number;
  /** Short verbatim snippet the claim is grounded in. Kept short -- this is evidence, not a copy of the source. */
  evidenceQuote: string;
}

export type ConfidenceLevel = "high" | "medium" | "low";

// ---------------------------------------------------------------------------
// Manuscript structure (EXTRACTED -- deterministic parser output)
// ---------------------------------------------------------------------------

export type BlockKind = "paragraph" | "dialogue" | "verse" | "heading" | "chapter_title";

export interface InlineSpan {
  text: string;
  emphasis?: "italic" | "bold";
}

export interface Block {
  id: string;
  kind: BlockKind;
  /** Plain text, for matching/search. */
  text: string;
  /** Structured spans, so italics/bold survive as more than a boolean on the whole block. */
  spans: InlineSpan[];
  /** True if this block contains at least one emphasized span. Cheap filter before walking spans. */
  hasEmphasis: boolean;
}

export interface Chapter {
  id: string;
  index: number;
  title: string;
  blocks: Block[];
}

export interface ManuscriptMetadata {
  title: string | null;
  author: string | null;
  sourceLanguage: string | null;
  sourceFormat?: string;
  sourceFilename?: string;
  /** Where in the raw source each metadata field was found, for the document profile view. */
  provenance: Partial<Record<"title" | "author" | "sourceLanguage", SourceLocation>>;
}

export interface ParsedManuscript {
  metadata: ManuscriptMetadata;
  chapters: Chapter[];
  /** Raw source text, preserved verbatim and never mutated by downstream analysis. */
  rawSource: string;
  /** Simple content hash of rawSource, so callers can detect if "the same manuscript" really is. */
  sourceHash: string;
}

// ---------------------------------------------------------------------------
// Term base (SUGGESTED by an LLM, promoted to CONFIRMED by a human)
// ---------------------------------------------------------------------------

export type TermCategory =
  | "character"
  | "place"
  | "organization"
  | "object"
  | "invented_word"
  | "coined_phrase"
  | "title"
  | "other";

export type TranslationPolicy = "do_not_translate" | "preserve_consistently" | "translate_normally";

export interface PronunciationNote {
  value: string | null;
  /** null when not confidently inferable -- never fabricated. */
  confidence: ConfidenceLevel | null;
  note: string;
}

export interface TermCandidate {
  id: string;
  canonicalForm: string;
  category: TermCategory;
  /** Every occurrence the extractor found, in source order. First is primary evidence. */
  occurrences: SourceLocation[];
  meaning: string;
  pronunciation: PronunciationNote;
  suggestedPolicy: TranslationPolicy;
  confidence: ConfidenceLevel;
  status: ProvenanceStatus; // "suggested" | "confirmed" | "rejected" for term candidates
  /** Evidence signals used by the deterministic post-filter; useful for audit and UI explanations. */
  evidenceSignals?: string[];
  memorySource?: "new" | "previously_approved";
  /** Present only once a human has acted on this candidate. */
  reviewedBy?: string;
  reviewedAt?: string;
  /** If the human edited the canonical form/policy on confirmation, the edited value lives here; canonicalForm above is left as the original suggestion for audit. */
  confirmedOverride?: {
    canonicalForm?: string;
    policy?: TranslationPolicy;
  };
}

export interface DoNotTranslateRule {
  id: string;
  /** The term this rule governs -- must reference a CONFIRMED TermCandidate. */
  termId: string;
  canonicalForm: string;
  policy: TranslationPolicy;
  caseSensitive: boolean;
  reason: string;
  scope: "this_manuscript";
}

export interface StyleNote {
  register: string;
  narrativeVoice: string;
  dialogue: string;
  tone: string;
  wordplay: string;
  verse: string;
  formatting: string;
  translationConsiderations: string;
  /** Manuscript-specific observations that don't fit the fixed fields above. */
  additionalNotes: string[];
  evidence?: SourceLocation[];
  status: ProvenanceStatus; // style notes are SUGGESTED until reviewed, same as terms
}

export interface FormattingRule {
  id: string;
  source: SourceLocation;
  formatting: "italic" | "bold" | "verse_structure" | "heading" | "dialogue_structure";
  meaning: string;
  translationRequirement: string;
}

// ---------------------------------------------------------------------------
// Translation packet (the deliverable handed to the translator)
// ---------------------------------------------------------------------------

export interface TranslationPacket {
  manuscriptTitle: string;
  targetLanguage: string;
  targetLocale?: string;
  cleanSourceHtml: string;
  termBase: TermCandidate[];
  doNotTranslateRules: DoNotTranslateRule[];
  styleNote: StyleNote;
  formattingGuidance: FormattingRule[];
  sourceMetadata: {
    filename: string | null;
    format: string | null;
    author: string | null;
    sourceLanguage: string | null;
  };
  generatedAt: string;
  sourceHash: string;
}

// ---------------------------------------------------------------------------
// Alignment (source chapter/block <-> returned translation)
// ---------------------------------------------------------------------------

export interface AlignedBlock {
  sourceChapterId: string;
  sourceBlockId: string;
  translatedBlockId: string | null;
  confidence: ConfidenceLevel;
  /** True when the aligner could not confidently match -- surfaced as REVIEW REQUIRED, never guessed past. */
  reviewRequired: boolean;
}

// ---------------------------------------------------------------------------
// QA findings (chapter-by-chapter mismatch report)
// ---------------------------------------------------------------------------

export type FindingCategory = "protected_term" | "formatting" | "structure" | "consistency";
export type FindingSeverity = "high" | "medium" | "low";

export interface Finding {
  id: string;
  chapterId: string;
  chapterTitle: string;
  category: FindingCategory;
  /**
   * Whether the violated rule was actually CONFIRMED at verification time.
   * A confirmed-rule violation is a hard mismatch. An unconfirmed-candidate
   * violation is still surfaced (missing it because no one reviewed it yet
   * is its own failure) but must never present with the authority of an
   * approved rule.
   */
  ruleStatus: ProvenanceStatus;
  severity: FindingSeverity;
  expected: string;
  actual: string;
  ruleDescription: string;
  sourceLocation: SourceLocation;
  translatedLocation: SourceLocation | null;
  recommendedAction: string;
  confidence: ConfidenceLevel;
  reviewStatus?: "open" | "approved" | "rejected" | "intentional" | "manual_review";
}

export interface ChapterQaSummary {
  chapterId: string;
  chapterTitle: string;
  status: "pass" | "issues";
  findingCount: number;
}

export interface TranslationQaReport {
  generatedAt: string;
  totalProtectedTerms: number;
  totalPassed: number;
  totalFindings: number;
  chapters: ChapterQaSummary[];
  findings: Finding[];
}

// ---------------------------------------------------------------------------
// Document integrity / diff (the "change only X" invariant)
// ---------------------------------------------------------------------------

export type ChangeKind = "text" | "formatting" | "structure" | "ordering" | "metadata";

export interface DocumentChange {
  kind: ChangeKind;
  location: string;
  before: string;
  after: string;
}

export interface DocumentDiffResult {
  changes: DocumentChange[];
  changedFieldCount: number;
}

export interface IntegrityCheckResult {
  expectedChangeCount: number;
  actualChangeCount: number;
  pass: boolean;
  unexpectedChanges: DocumentChange[];
  diff: DocumentDiffResult;
}
