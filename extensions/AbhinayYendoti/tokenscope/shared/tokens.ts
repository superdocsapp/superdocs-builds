import { encode } from "gpt-tokenizer";
import type {
  Comparison,
  DocumentSnapshot,
  JobWork,
  Measurement,
  Savings,
  Selection,
  TokenCount
} from "./types.js";

/**
 * Token arithmetic.
 *
 * Three different things get called "tokens" here and they must never be
 * conflated:
 *
 *   1. Text tokens     how many tokens a piece of text is worth. Produced by a
 *                      real BPE tokenizer (o200k_base) over the exact string.
 *                      Deterministic, reproducible, free.
 *   2. Reported cost   how many tokens SuperDocs said a job consumed. Only
 *                      SuperDocs can know this; TokenScope reads it back off the
 *                      job record and never computes it.
 *   3. Written output  how much text a job actually emitted, tokenized with (1)
 *                      from the job's own returned changes.
 *
 * (1) is never presented as (2). (3) exists because (2) turned out to be
 * unreliable on large jobs - see README, "Token methodology".
 */

/** o200k_base is not necessarily SuperDocs' tokenizer. See README, "Limitations". */
export const TEXT_TOKENIZER = "o200k_base (gpt-tokenizer)";

export function countTextTokens(text: string): number {
  if (text.length === 0) return 0;
  return encode(text).length;
}

export function documentText(document: DocumentSnapshot): string {
  return document.paragraphs.map((p) => p.text).join("\n\n");
}

export function tokenizeText(text: string, what: string): TokenCount {
  return {
    tokens: countTextTokens(text),
    source: "tokenized",
    method: `${what} tokenized locally with ${TEXT_TOKENIZER}`
  };
}

export function savings(wholeDocument: number, surgical: number): Savings {
  const tokens = wholeDocument - surgical;
  return { tokens, ratio: wholeDocument === 0 ? 0 : tokens / wholeDocument };
}

function compare(
  label: string,
  note: string,
  surgical: TokenCount | null,
  wholeDocument: TokenCount | null
): Comparison {
  return {
    label,
    note,
    surgical,
    wholeDocument,
    savings:
      surgical === null || wholeDocument === null
        ? null
        : savings(wholeDocument.tokens, surgical.tokens)
  };
}

/**
 * The whole-document counterfactual for the reported-cost comparison, derived
 * from measured values.
 *
 * A whole-document regeneration has to do everything the surgical edit did, and
 * then also read the rest of the document into the prompt and re-emit it:
 *
 *     estimate = reported_surgical + 2 x (document_tokens - selection_tokens)
 *
 * `reported_surgical` carries the fixed agent overhead, so both sides of the
 * comparison include it and the difference is attributable to document size
 * alone. The factor of two is the read and the write of the untouched remainder.
 *
 * This is an estimate and is labelled as one everywhere it appears. Running the
 * regeneration for real replaces it with a measured number.
 */
export function estimateWholeDocumentTokens(
  surgicalTokens: number,
  documentTokens: number,
  selectionTokens: number
): TokenCount {
  const remainder = Math.max(0, documentTokens - selectionTokens);

  return {
    tokens: surgicalTokens + 2 * remainder,
    source: "estimated",
    method:
      "reported surgical cost + 2 x (document - selection) text tokens: the untouched " +
      "remainder has to be read into the prompt and written back out again"
  };
}

export interface MeasureInput {
  document: DocumentSnapshot;
  selection: Selection;
  /** What the surgical job wrote, and how many sections it touched. */
  surgicalWork: JobWork;
  /** SuperDocs' reported cost for the surgical job. null when it reported none. */
  reportedSurgicalTokens: number | null;
  /** The same two figures for a real whole-document regeneration, if one ran. */
  wholeDocumentWork?: JobWork | undefined;
  reportedWholeDocumentTokens?: number | null | undefined;
}

export function measure(input: MeasureInput): Measurement {
  const selection = tokenizeText(input.selection.text, "selected text");
  const document = tokenizeText(documentText(input.document), "document body");

  const reportedSurgical: TokenCount | null =
    input.reportedSurgicalTokens === null
      ? null
      : {
          tokens: input.reportedSurgicalTokens,
          source: "measured",
          method: "reported by SuperDocs as metadata.cumulative_tokens on the rewrite job"
        };

  const ranForReal = input.wholeDocumentWork !== undefined;

  let reportedWhole: TokenCount | null;

  if (ranForReal) {
    reportedWhole =
      input.reportedWholeDocumentTokens === null || input.reportedWholeDocumentTokens === undefined
        ? null
        : {
            tokens: input.reportedWholeDocumentTokens,
            source: "measured",
            method:
              "reported by SuperDocs as metadata.cumulative_tokens on a real whole-document " +
              "regeneration of the same document, run in a throwaway session"
          };
  } else {
    reportedWhole =
      reportedSurgical === null
        ? null
        : estimateWholeDocumentTokens(reportedSurgical.tokens, document.tokens, selection.tokens);
  }

  /**
   * How much a regeneration would have had to write, when none was run: the
   * whole document. That is what "regenerate the document" means, and it is
   * tokenized from the document the user actually has.
   */
  const writtenWhole: TokenCount =
    input.wholeDocumentWork?.output ??
    ({
      tokens: document.tokens,
      source: "estimated",
      method:
        "a full regeneration has to emit every paragraph, so this is the document body " +
        `tokenized with ${TEXT_TOKENIZER}`
    } satisfies TokenCount);

  return {
    selection,
    document,
    reported: compare(
      "What SuperDocs reported it cost",
      "SuperDocs' own metadata.cumulative_tokens for each job. It is a context measure " +
        "rather than a running total, and it is not always reported on very large jobs.",
      reportedSurgical,
      reportedWhole
    ),
    written: compare(
      "How much text had to be written",
      "Tokenized from the text each job actually returned. Available on every job, at " +
        "every document size.",
      input.surgicalWork.output,
      writtenWhole
    ),
    sections: {
      surgical: input.surgicalWork.sectionsChanged,
      wholeDocument: input.wholeDocumentWork?.sectionsChanged ?? null
    }
  };
}
