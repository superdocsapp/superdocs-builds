import type {
  Block,
  Chapter,
  ConfidenceLevel,
  DoNotTranslateRule,
  Finding,
  FindingSeverity,
  ProvenanceStatus,
  SourceLocation,
  TermCandidate,
} from "../types.js";
import type { ChapterAlignmentResult } from "../align/alignTranslation.js";

/**
 * The lifecycle enforcement point.
 *
 * There is exactly one function that can produce a CONFIRMED term, and it
 * requires the term to already be in "suggested" status and requires a
 * named reviewer. Nothing in this codebase promotes a term automatically --
 * see buildDoNotTranslateRules below, which only ever reads confirmed
 * terms, never writes them.
 */
export function confirmTerm(
  term: TermCandidate,
  reviewedBy: string,
  override?: { canonicalForm?: string; policy?: TermCandidate["suggestedPolicy"] },
): TermCandidate {
  if (term.status !== "suggested") {
    throw new Error(
      `Cannot confirm term "${term.canonicalForm}" (id ${term.id}): status is "${term.status}", not "suggested". ` +
        `Only a suggested candidate can be confirmed -- this prevents re-confirming a term that was already rejected without a fresh review.`,
    );
  }
  return {
    ...term,
    status: "confirmed",
    reviewedBy,
    reviewedAt: new Date().toISOString(),
    confirmedOverride: override,
  };
}

export function rejectTerm(term: TermCandidate, reviewedBy: string): TermCandidate {
  if (term.status !== "suggested") {
    throw new Error(`Cannot reject term "${term.canonicalForm}" (id ${term.id}): status is "${term.status}", not "suggested".`);
  }
  return { ...term, status: "rejected", reviewedBy, reviewedAt: new Date().toISOString() };
}

/** Builds enforceable rules from CONFIRMED terms only. Suggested and rejected terms produce no rule -- an unreviewed AI guess never gets enforcement authority. */
export function buildDoNotTranslateRules(terms: TermCandidate[]): DoNotTranslateRule[] {
  return terms
    .filter((t) => t.status === "confirmed")
    .map((t) => {
      const canonicalForm = t.confirmedOverride?.canonicalForm ?? t.canonicalForm;
      const policy = t.confirmedOverride?.policy ?? t.suggestedPolicy;
      return {
        id: `rule-${t.id}`,
        termId: t.id,
        canonicalForm,
        policy,
        caseSensitive: true,
        reason: t.meaning || `${t.category} identified in the manuscript`,
        scope: "this_manuscript" as const,
      };
    })
    .filter((r) => r.policy !== "translate_normally"); // a rule whose policy is "translate normally" isn't a protection rule at all
}

// ---------------------------------------------------------------------------
// Verification
// ---------------------------------------------------------------------------

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function occurrenceRegex(term: string, caseSensitive: boolean): RegExp {
  const escaped = escapeRegExp(term);
  // Manual boundary check instead of \b: \b is ASCII-word-char based and
  // mishandles the curly apostrophes and accented letters this manuscript
  // actually contains (e.g. "Mock Turtle’s"). (?<![...]) / (?![...]) lookaround
  // against a broader "word-ish" character class is more correct here.
  const wordish = "\\p{L}\\p{N}_’'";
  const pattern = `(?<![${wordish}])${escaped}(?![${wordish}])`;
  return new RegExp(pattern, caseSensitive ? "gu" : "giu");
}

export function countOccurrences(text: string, term: string, caseSensitive: boolean): number {
  const matches = text.match(occurrenceRegex(term, caseSensitive));
  return matches ? matches.length : 0;
}

/** Plain Levenshtein edit distance. Used only as a "did this look like a near-miss mistranslation" signal for finding evidence -- never to silently auto-correct anything. */
export function levenshteinDistance(a: string, b: string): number {
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = 0; i <= a.length; i++) dp[i]![0] = i;
  for (let j = 0; j <= b.length; j++) dp[0]![j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[i]![j] = Math.min(dp[i - 1]![j]! + 1, dp[i]![j - 1]! + 1, dp[i - 1]![j - 1]! + cost);
    }
  }
  return dp[a.length]![b.length]!;
}

/** Finds the word in `text` most similar to `term` by edit distance, as evidence for what a protected term may have been mistranslated into. Returns null if nothing is close enough to be useful. */
function findClosestWord(text: string, term: string): { word: string; distance: number } | null {
  const words = text.match(/[\p{L}\p{N}’'-]+/gu) ?? [];
  let best: { word: string; distance: number } | null = null;
  for (const w of words) {
    if (Math.abs(w.length - term.length) > 3) continue; // cheap prune
    const d = levenshteinDistance(w.toLowerCase(), term.toLowerCase());
    if (d === 0) continue; // exact match would have been caught by countOccurrences already
    if (d <= 2 && (!best || d < best.distance)) best = { word: w, distance: d };
  }
  return best;
}

function blockById(chapter: Chapter | undefined, blockId: string | null): Block | null {
  if (!chapter || !blockId) return null;
  return chapter.blocks.find((b) => b.id === blockId) ?? null;
}

function locationFor(chapter: Chapter, block: Block | null, fallbackQuote: string): SourceLocation {
  const blockIndex = block ? chapter.blocks.findIndex((b) => b.id === block.id) : -1;
  return {
    chapterId: chapter.id,
    chapterTitle: chapter.title,
    blockIndex,
    evidenceQuote: (block?.text ?? fallbackQuote).slice(0, 120),
  };
}

interface VerifyOneTermInput {
  canonicalForm: string;
  caseSensitive: boolean;
  ruleStatus: ProvenanceStatus;
  ruleDescription: string;
  severity: FindingSeverity;
  confidence: ConfidenceLevel;
  idPrefix: string;
}

function verifyOneTermAcrossManuscript(
  input: VerifyOneTermInput,
  sourceChapters: Chapter[],
  translatedChaptersById: Map<string, Chapter>,
  chapterAlignments: ChapterAlignmentResult[],
): Finding[] {
  const findings: Finding[] = [];
  let findingSeq = 0;

  for (const sourceChapter of sourceChapters) {
    const alignment = chapterAlignments.find((a) => a.sourceChapterId === sourceChapter.id);
    const translatedChapter = alignment?.translatedChapterId ? translatedChaptersById.get(alignment.translatedChapterId) : undefined;

    const sourceOccurrences = sourceChapter.blocks
      .flatMap((sourceBlock) => {
        const count = countOccurrences(sourceBlock.text, input.canonicalForm, input.caseSensitive);
        return Array.from({ length: count }, () => sourceBlock);
      });

    if (sourceOccurrences.length === 0) continue;

    const sourceBlock = sourceOccurrences[0]!;
    if (!translatedChapter) {
      findings.push({
        id: `${input.idPrefix}-${findingSeq++}`,
        chapterId: sourceChapter.id,
        chapterTitle: sourceChapter.title,
        category: "protected_term",
        ruleStatus: input.ruleStatus,
        severity: input.severity,
        expected: input.canonicalForm,
        actual: "(chapter missing entirely from the returned translation)",
        ruleDescription: input.ruleDescription,
        sourceLocation: locationFor(sourceChapter, sourceBlock, sourceBlock.text),
        translatedLocation: null,
        recommendedAction: "Confirm the chapter was included in the returned translation and re-submit.",
        confidence: "high",
      });
      continue;
    }

    // Count at chapter scope rather than relying on paragraph alignment. Translators
    // routinely split/merge sentences, so chapter-level verification avoids false
    // negatives caused by a perfectly valid reflow.
    const translatedText = translatedChapter.blocks.map((b) => b.text).join(" ");
    const translatedCount = countOccurrences(translatedText, input.canonicalForm, input.caseSensitive);
    if (translatedCount >= sourceOccurrences.length) continue;

    let translatedBlock: Block | null = null;
    for (const candidate of translatedChapter.blocks) {
      if (countOccurrences(candidate.text, input.canonicalForm, input.caseSensitive) > 0) {
        translatedBlock = candidate;
        break;
      }
    }
    if (!translatedBlock) {
      const aligned = alignment?.blockAlignments.find((ba) => ba.sourceBlockId === sourceBlock.id);
      translatedBlock = blockById(translatedChapter, aligned?.translatedBlockId ?? null);
    }

    const closest = translatedBlock ? findClosestWord(translatedBlock.text, input.canonicalForm) : findClosestWord(translatedText, input.canonicalForm);
    findings.push({
      id: `${input.idPrefix}-${findingSeq++}`,
      chapterId: sourceChapter.id,
      chapterTitle: sourceChapter.title,
      category: "protected_term",
      ruleStatus: input.ruleStatus,
      severity: input.severity,
      expected: input.canonicalForm,
      actual: closest ? closest.word : "(term not found in returned chapter)",
      ruleDescription: input.ruleDescription,
      sourceLocation: locationFor(sourceChapter, sourceBlock, sourceBlock.text),
      translatedLocation: translatedBlock ? locationFor(translatedChapter, translatedBlock, translatedBlock.text) : null,
      recommendedAction:
        input.ruleStatus === "confirmed"
          ? "Restore the approved canonical term and re-run chapter QA."
          : "This term has not been reviewed yet -- confirm whether it should be protected, then re-run verification.",
      confidence: alignment?.blockAlignments.some((ba) => ba.reviewRequired) ? "low" : "high",
    });
  }

  return findings;
}

export interface VerifyProtectedTermsInput {
  /** Enforceable rules -- output of buildDoNotTranslateRules, so already confirmed-only. */
  rules: DoNotTranslateRule[];
  /**
   * The full candidate set, any status. Suggested (not yet reviewed) terms
   * are still checked -- missing a change to an unreviewed candidate is its
   * own failure -- but their findings are marked ruleStatus: "suggested"
   * and carry a lower severity and a "please decide" action, never the
   * authority of an approved rule. Rejected terms are skipped entirely.
   */
  allTerms: TermCandidate[];
  sourceChapters: Chapter[];
  translatedChapters: Chapter[];
  chapterAlignments: ChapterAlignmentResult[];
}

export function verifyProtectedTerms(input: VerifyProtectedTermsInput): Finding[] {
  const translatedChaptersById = new Map(input.translatedChapters.map((c) => [c.id, c]));
  const findings: Finding[] = [];

  for (const rule of input.rules) {
    if (rule.policy === "translate_normally") continue;
    findings.push(
      ...verifyOneTermAcrossManuscript(
        {
          canonicalForm: rule.canonicalForm,
          caseSensitive: rule.caseSensitive,
          ruleStatus: "confirmed",
          ruleDescription: `${rule.reason} (${rule.policy})`,
          severity: "high",
          confidence: "high",
          idPrefix: `finding-${rule.id}`,
        },
        input.sourceChapters,
        translatedChaptersById,
        input.chapterAlignments,
      ),
    );
  }

  const confirmedOrRejectedIds = new Set(input.allTerms.filter((t) => t.status !== "suggested").map((t) => t.id));
  const suggestedTerms = input.allTerms.filter((t) => t.status === "suggested" && !confirmedOrRejectedIds.has(t.id));
  for (const term of suggestedTerms) {
    if (term.suggestedPolicy === "translate_normally") continue;
    findings.push(
      ...verifyOneTermAcrossManuscript(
        {
          canonicalForm: term.canonicalForm,
          caseSensitive: true,
          ruleStatus: "suggested",
          ruleDescription: `${term.meaning || term.category} -- suggested, not yet reviewed (${term.suggestedPolicy})`,
          severity: "low",
          confidence: term.confidence,
          idPrefix: `finding-suggested-${term.id}`,
        },
        input.sourceChapters,
        translatedChaptersById,
        input.chapterAlignments,
      ),
    );
  }

  return findings;
}
