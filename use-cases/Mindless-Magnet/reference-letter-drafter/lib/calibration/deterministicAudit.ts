/**
 * Deterministic half of the calibration audit.
 *
 * No model call, no key, no network, no cost. Runs in about a millisecond and
 * gives the same answer every time, which is what makes it testable and what
 * makes it safe to run on every draft.
 *
 * It cannot catch subtle inflation ("a valued member of the team" reads warmer
 * than a reluctant writer meant). That is the model verifier's job. This layer
 * catches the blatant cases, which — in the letters this build has produced so
 * far — is most of them. Two layers, deliberately: a hard-coded defense
 * alongside intelligent logic, not instead of it.
 */

import { BANDS } from "./lexicon";
import type { LexiconRule } from "./lexicon";
import type { CalibrationFinding, StrengthBand } from "../types";

/** Escape a literal phrase for use inside a RegExp. */
function escape(phrase: string): string {
  return phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Word-boundary match. `\b` alone is wrong for multi-word phrases that end in
 * punctuation-adjacent tokens, so the boundary is asserted explicitly on both
 * ends against a non-word character or string edge.
 */
function phraseRegex(phrase: string): RegExp {
  return new RegExp(`(?<![\\w-])${escape(phrase)}(?![\\w-])`, "gi");
}

const CONTEXT_WINDOW = 40;

function isGuardedByContext(text: string, index: number, length: number, notNear: string[]): boolean {
  const start = Math.max(0, index - CONTEXT_WINDOW);
  const end = Math.min(text.length, index + length + CONTEXT_WINDOW);
  const window = text.slice(start, end).toLowerCase();
  return notNear.some((word) => new RegExp(`(?<![\\w-])${escape(word)}(?![\\w-])`, "i").test(window));
}

/** One sentence of surrounding context, so the writer can see what fired. */
function excerptAround(text: string, index: number, length: number): string {
  const start = Math.max(0, text.lastIndexOf(".", index) + 1);
  const dotAfter = text.indexOf(".", index + length);
  const end = dotAfter === -1 ? Math.min(text.length, index + length + 120) : dotAfter + 1;
  return text.slice(start, end).trim();
}

function findBannedPhrases(text: string, rules: LexiconRule[], band: StrengthBand): CalibrationFinding[] {
  const findings: CalibrationFinding[] = [];
  const seen = new Set<string>();

  for (const rule of rules) {
    const re = phraseRegex(rule.phrase);
    let match: RegExpExecArray | null;
    while ((match = re.exec(text)) !== null) {
      if (rule.notNear && isGuardedByContext(text, match.index, match[0].length, rule.notNear)) {
        continue;
      }
      // One finding per phrase per letter. Ten instances of "outstanding" is
      // the same problem reported ten times, and a review list nobody reads is
      // a review list that gets rubber-stamped.
      const key = rule.phrase.toLowerCase();
      if (seen.has(key)) break;
      seen.add(key);

      findings.push({
        id: `band-${key.replace(/\s+/g, "-")}`,
        kind: "band_violation",
        severity: "high",
        title: `"${match[0]}" reads warmer than the declared band`,
        detail: `${rule.why} You declared this letter as "${BANDS[band].label}".`,
        excerpt: excerptAround(text, match.index, match[0].length),
        source: "lexicon",
      });
      break;
    }
  }

  return findings;
}

function findMissingHedges(text: string, band: StrengthBand): CalibrationFinding[] {
  const spec = BANDS[band];
  if (!spec.expectedHedges?.length) return [];

  const present = spec.expectedHedges.some((hedge) => phraseRegex(hedge).test(text));
  if (present) return [];

  return [
    {
      id: "band-no-qualifier",
      kind: "band_violation",
      severity: "high",
      title: "Nothing in this letter qualifies the praise",
      detail:
        `You declared this letter as "${spec.label}", but it contains no hedge, caveat or ` +
        "limitation anywhere. A reader has no way to tell it apart from an unreserved endorsement. " +
        "This is the most common way a lukewarm reference is silently inflated.",
      source: "lexicon",
    },
  ];
}

/**
 * Reservations the writer typed must survive into the letter. Matching is
 * intentionally loose (content words, not exact strings) because the letter is
 * expected to rephrase, not to copy. A reservation is treated as carried if a
 * majority of its distinctive words appear somewhere in the letter.
 */
const STOPWORDS = new Set([
  "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been", "to", "of",
  "in", "on", "at", "for", "with", "that", "this", "it", "as", "he", "she", "they", "his",
  "her", "their", "them", "him", "not", "no", "can", "could", "would", "should", "has", "have",
  "had", "do", "does", "did", "i", "we", "you", "my", "our", "sometimes", "very", "more", "than",
]);

function contentWords(s: string): string[] {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 3 && !STOPWORDS.has(w));
}

function findDroppedReservations(text: string, reservations: string): CalibrationFinding[] {
  const trimmed = reservations.trim();
  if (!trimmed) return [];

  const lower = text.toLowerCase();
  const findings: CalibrationFinding[] = [];

  const clauses = trimmed
    .split(/[.;\n]+/)
    .map((c) => c.trim())
    .filter((c) => c.length > 0);

  clauses.forEach((clause, i) => {
    const words = contentWords(clause);
    if (words.length === 0) return;
    const hits = words.filter((w) => lower.includes(w)).length;
    if (hits / words.length >= 0.5) return;

    findings.push({
      id: `reservation-dropped-${i}`,
      kind: "dropped_reservation",
      severity: "high",
      title: "A reservation you stated does not appear in the letter",
      detail:
        "You wrote this as a reservation, and the letter does not reflect it. Omitting it is the " +
        "difference between a calibrated reference and a generous one.",
      excerpt: clause,
      source: "lexicon",
    });
  });

  return findings;
}

export interface DeterministicAuditInput {
  /** Plain text of the letter. Pass text, not HTML. */
  text: string;
  band: StrengthBand;
  reservations: string;
}

export function runDeterministicAudit(input: DeterministicAuditInput): CalibrationFinding[] {
  const { text, band, reservations } = input;
  if (!text.trim()) return [];

  return [
    ...findBannedPhrases(text, BANDS[band].banned, band),
    ...findMissingHedges(text, band),
    ...findDroppedReservations(text, reservations),
  ];
}
