/**
 * The contract between the TokenScope server, the task pane and the benchmark.
 *
 * Every token number that crosses this boundary carries its own provenance in a
 * `source` field. Nothing in the UI is allowed to render a count without saying
 * where it came from, which is the whole point of the product.
 */

/** Where a token count came from. The UI renders a different badge per value. */
export type TokenSource =
  /** Reported by SuperDocs for a real job it ran. Not computed by us. */
  | "measured"
  /** Tokenized locally with a real BPE tokenizer from text that really exists. */
  | "tokenized"
  /** Derived from measured and tokenized values. Never a guess, but not observed. */
  | "estimated";

export interface TokenCount {
  tokens: number;
  source: TokenSource;
  /** One sentence a reviewer can check the number against. */
  method: string;
}

export interface Savings {
  tokens: number;
  ratio: number;
}

/** A paragraph of the document as the host (Word, or the demo surface) sees it. */
export interface Paragraph {
  id: string;
  text: string;
}

export interface DocumentSnapshot {
  paragraphs: Paragraph[];
}

/** What the user selected, resolved against the document. */
export interface Selection {
  /** Ids of the paragraphs the selection covers, in document order. */
  paragraphIds: string[];
  /** The selected text itself. */
  text: string;
}

/** One proposed edit, exactly as SuperDocs returned it. Not applied yet. */
export interface ProposedChange {
  changeId: string;
  chunkId: string;
  operation: string;
  oldHtml: string;
  newHtml: string;
  oldText: string;
  newText: string;
  explanation: string;
}

/**
 * What a job actually had to do, read off the changes it returned.
 *
 * `sectionsChanged` and `output` come from the job's own result: how many
 * sections it rewrote, and how much text it had to emit to do it. Unlike the
 * provider's own counter these are available on every job and they behave
 * monotonically with document size. See README, "Token methodology".
 */
export interface JobWork {
  sectionsChanged: number;
  output: TokenCount;
}

/**
 * One side-by-side comparison: surgical against whole-document.
 *
 * `null` means the number does not exist rather than that it is zero, and the UI
 * has to say so. TokenScope shows two of these - what SuperDocs reported each
 * operation cost, and how much text each operation had to write.
 */
export interface Comparison {
  label: string;
  note: string;
  surgical: TokenCount | null;
  wholeDocument: TokenCount | null;
  savings: Savings | null;
}

export interface Measurement {
  /** Tokens in the selected text alone. Context for the reader, not a cost. */
  selection: TokenCount;
  /** Tokens in the whole document body. Context for the reader, not a cost. */
  document: TokenCount;
  /** What SuperDocs reported each operation cost. Absent on some large jobs. */
  reported: Comparison;
  /** How much text each operation had to write. Always available. */
  written: Comparison;
  /** Sections each operation changed. 1 versus the whole document. */
  sections: { surgical: number; wholeDocument: number | null };
}

/** Result of running the whole-document counterfactual for real. */
export interface WholeDocumentRun {
  sessionId: string;
  jobId: string;
  /** null when SuperDocs reported no token count for the job. */
  reportedTokens: number | null;
  work: JobWork;
  elapsedMs: number;
}

export interface AccountStatus {
  configured: boolean;
  tier?: string;
  quota?: { monthlyLimit: number; used: number; remaining: number; resetsAt: string | null };
  /** Present when the key is missing or rejected. */
  problem?: string;
}

export interface ApiErrorBody {
  error: { code: string; message: string; hint?: string };
}
