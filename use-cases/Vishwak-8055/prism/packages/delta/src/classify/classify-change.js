// @ts-check
/**
 * Deterministic classification layer.
 *
 * This is PRISM DELTA's actual "upgrade" over SuperDoc's base diff contract:
 * the real diff.compare only reports coarse hasChanges booleans per
 * component (body/comments/styles/numbering/headerFooters). Everything in
 * this file turns a detected text change into one of the categories the
 * PRISM DELTA spec asks for: numeric, date, formatting, structural, or
 * (honestly) "needs semantic review" when no deterministic rule applies.
 *
 * What is deliberately NOT here: a claim to judge legal/business
 * materiality of prose rewording. "reasonable efforts" -> "best efforts" is
 * flagged as an *obligation-language signal*, not scored as "high risk" —
 * that judgment needs either a human or a model in the loop, per the
 * directive's own instruction to use models for semantic reasoning and
 * deterministic code for deterministic tasks, and to never guess silently
 * on material ambiguity.
 */
import { wordDiff } from '@prism/core';

// Comma groups are constrained to proper 3-digit thousands separators
// (\d{1,3}(?:,\d{3})*), not a bare [\d,]* — the loose version was greedily
// swallowing the sentence's own trailing comma into the match (e.g.
// "$50,000," instead of "$50,000"), which showed up as a doubled comma in
// the human-readable "why" text. Caught by actually running the CLI.
const CURRENCY_OR_NUMBER_RE = /\$\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d{1,3}(?:,\d{3})*(?:\.\d+)?\s?%|\d{1,3}(?:,\d{3})*(?:\.\d+)?/g;

const MONTH_DATE_RE = /\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b/gi;
const NUMERIC_DATE_RE = /\b\d{1,2}\/\d{1,2}\/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b/g;

// Small, explicitly-curated obligation-language signal terms. Presence is a
// *signal to route for review*, not a materiality verdict.
const OBLIGATION_TERMS = [
  'shall',
  'must',
  'may',
  'reasonable efforts',
  'best efforts',
  'indemnify',
  'indemnification',
  'warrant',
  'warranty',
  'liable',
  'liability',
  'terminate',
  'termination',
  'sole discretion',
  'material breach',
  'condition precedent',
];

function extractNumbers(text) {
  return [...text.matchAll(CURRENCY_OR_NUMBER_RE)].map((m) => m[0]);
}

function extractDates(text) {
  const months = [...text.matchAll(MONTH_DATE_RE)].map((m) => m[0]);
  const numeric = [...text.matchAll(NUMERIC_DATE_RE)].map((m) => m[0]);
  return [...months, ...numeric];
}

function findObligationTerms(text) {
  const lower = text.toLowerCase();
  return OBLIGATION_TERMS.filter((term) => lower.includes(term));
}

function sameSet(a, b) {
  if (a.length !== b.length) return false;
  const sa = [...a].sort();
  const sb = [...b].sort();
  return sa.every((v, i) => v === sb[i]);
}

/** Percent delta for a single numeric-token pair, used to grade materiality. */
function numericMagnitudeIsSmall(baseNums, targetNums) {
  const toFloat = (s) => Number(String(s).replace(/[^0-9.]/g, ''));
  if (baseNums.length !== 1 || targetNums.length !== 1) return false; // only score simple 1:1 swaps
  const b = toFloat(baseNums[0]);
  const t = toFloat(targetNums[0]);
  if (!Number.isFinite(b) || !Number.isFinite(t) || b === 0) return false;
  return Math.abs(t - b) / Math.abs(b) < 0.02; // <2% delta treated as immaterial rounding
}

/**
 * Classify a paragraph believed to be a modification of another paragraph.
 */
export function classifyModifiedParagraph(base, target) {
  const parts = wordDiff(base.text, target.text);

  // Detection scans the FULL paragraph text on each side, not the word-diff's
  // isolated changed fragments. A diff like "January 1, 2026" -> "March 1,
  // 2026" only isolates the token "January" (day and year are common text),
  // so a fragment-only regex would silently miss the date change. Full-text
  // set comparison catches it regardless of how the word tokenizer split
  // things. `parts` is still returned in the result for transparency.
  const baseNums = extractNumbers(base.text);
  const targetNums = extractNumbers(target.text);
  const baseDates = extractDates(base.text);
  const targetDates = extractDates(target.text);
  const baseObligations = findObligationTerms(base.text);
  const targetObligations = findObligationTerms(target.text);
  const obligationSignal = !sameSet(baseObligations, targetObligations);

  const numbersChanged = !sameSet(baseNums, targetNums);
  const datesChanged = !sameSet(baseDates, targetDates);

  /** @type {{category: string, materiality: string, why: string}[]} */
  const findings = [];

  if (datesChanged) {
    findings.push({
      category: 'date',
      materiality: 'material',
      why: `Date changed from ${baseDates.join(', ')} to ${targetDates.join(', ')}.`,
    });
  }
  if (numbersChanged) {
    const small = numericMagnitudeIsSmall(baseNums, targetNums);
    findings.push({
      category: 'numeric',
      materiality: small ? 'minor' : 'material',
      why: `Numeric value changed from ${baseNums.join(', ')} to ${targetNums.join(', ')}${small ? ' (small magnitude, likely immaterial)' : ''}.`,
    });
  }
  if (obligationSignal) {
    findings.push({
      category: 'semantic',
      materiality: 'review-required',
      why: `Obligation-language terms changed (before: [${baseObligations.join(', ') || 'none'}], after: [${targetObligations.join(', ') || 'none'}]). Legal/business materiality needs human or model review — not scored automatically.`,
    });
  }
  if (findings.length === 0) {
    findings.push({
      category: 'semantic',
      materiality: 'review-required',
      why: 'Text changed but matched no deterministic rule (not a detected number, date, or known obligation term). Requires semantic review — PRISM DELTA does not guess at this tier.',
    });
  }

  return {
    type: 'modified',
    paragraphIndex: { base: base.index, target: target.index },
    baseText: base.text,
    targetText: target.text,
    wordDiff: parts,
    findings,
  };
}

/** Formatting fingerprint for run-level comparison. */
function formattingSignature(paragraph) {
  return JSON.stringify({
    styleId: paragraph.styleId,
    runs: paragraph.runs.map((r) => ({ bold: r.bold, italic: r.italic, underline: r.underline })),
  });
}

/**
 * A "common" (identical text) pair can still differ in formatting only.
 * Returns null when there is truly no change.
 */
export function classifyCommonPair(base, target) {
  if (formattingSignature(base) === formattingSignature(target)) return null;
  return {
    type: 'formatting',
    paragraphIndex: { base: base.index, target: target.index },
    baseText: base.text,
    targetText: target.text,
    findings: [
      {
        category: 'formatting',
        materiality: 'cosmetic',
        why: 'Text is identical; only run formatting or paragraph style changed. Not a substantive change.',
      },
    ],
  };
}

/** Pure add/remove blocks with no adjacent pairing candidate — structural. */
export function classifyStructuralBlock(kind, items) {
  return {
    type: kind === 'added' ? 'structural-add' : 'structural-remove',
    items: items.map((p) => ({ index: p.index, text: p.text })),
    findings: [
      {
        category: 'structural',
        materiality: 'review-required',
        why: `${items.length} paragraph(s) ${kind === 'added' ? 'added' : 'removed'} with no matching counterpart. Could be boilerplate or a new/removed clause — PRISM DELTA does not guess which; flagged for review.`,
      },
    ],
  };
}
