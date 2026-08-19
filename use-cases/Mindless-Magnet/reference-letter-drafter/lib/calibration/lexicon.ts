/**
 * Band calibration lexicon.
 *
 * This file is DATA, not logic. Adding a new band, a new banned phrase, or a
 * new hedge requirement is an edit here and nothing else — no code change, no
 * redeploy of the audit engine. That is deliberate: the vocabulary of reference
 * letters differs by country, discipline and era, and a US academic letter
 * calibrates differently from a UK employment reference.
 *
 * Phrases are matched case-insensitively on word boundaries. `context` is an
 * optional negative lookaround guard: a phrase only fires when it is NOT
 * adjacent to one of these words, which is how "outstanding balance" avoids
 * being flagged as a superlative.
 */

import type { StrengthBand } from "../types";

export interface LexiconRule {
  /** Literal phrase, matched case-insensitively on word boundaries. */
  phrase: string;
  /**
   * Words that, if adjacent to the phrase, mean it is being used in a
   * non-evaluative sense and should NOT be flagged.
   */
  notNear?: string[];
  /** Shown to the writer so the finding explains itself. */
  why: string;
}

export interface BandSpec {
  id: StrengthBand;
  /** Human label shown in the UI. */
  label: string;
  /**
   * Ordinal position, used for drift arithmetic in the eval harness.
   * Higher = warmer. Drift is measured in these units.
   */
  rank: number;
  /** One line the drafting model is given as the band contract. */
  contract: string;
  /** Phrases that must not appear in a letter of this band. */
  banned: LexiconRule[];
  /**
   * If set, a letter of this band that contains none of these hedging /
   * qualifying markers is suspicious: it reads warmer than it was meant to.
   */
  expectedHedges?: string[];
}

/** Phrases that are unconditionally the top of the scale. */
const SUPERLATIVES: LexiconRule[] = [
  { phrase: "without reservation", why: "An unqualified endorsement. Only honest at the top band." },
  { phrase: "without hesitation", why: "An unqualified endorsement. Only honest at the top band." },
  { phrase: "unreservedly", why: "An unqualified endorsement. Only honest at the top band." },
  { phrase: "highest possible recommendation", why: "Explicitly the top of the scale." },
  { phrase: "my highest recommendation", why: "Explicitly the top of the scale." },
  { phrase: "in the strongest possible terms", why: "Explicitly the top of the scale." },
  { phrase: "one of the best", why: "A ranking claim that puts the subject at the top." },
  { phrase: "one of the finest", why: "A ranking claim that puts the subject at the top." },
  { phrase: "one of the strongest", why: "A ranking claim that puts the subject at the top." },
  { phrase: "the best student", why: "A ranking claim that puts the subject at the top." },
  { phrase: "the best employee", why: "A ranking claim that puts the subject at the top." },
  {
    phrase: "outstanding",
    notNear: ["balance", "invoice", "debt", "payment", "amount", "shares", "issue", "issues"],
    why: "A top-band adjective.",
  },
  { phrase: "exceptional", why: "A top-band adjective." },
  { phrase: "extraordinary", why: "A top-band adjective." },
  { phrase: "brilliant", why: "A top-band adjective." },
  { phrase: "phenomenal", why: "A top-band adjective." },
  { phrase: "world-class", why: "A top-band adjective." },
  { phrase: "unparalleled", why: "A top-band adjective." },
  { phrase: "flawless", why: "A top-band adjective." },
  { phrase: "impeccable", why: "A top-band adjective." },
  { phrase: "second to none", why: "A top-band ranking claim." },
];

/** Warmth markers: honest above the middle, dishonest in a lukewarm letter. */
const ENTHUSIASM: LexiconRule[] = [
  { phrase: "delighted", why: "An enthusiasm marker. A lukewarm reference is not delighted." },
  { phrase: "thrilled", why: "An enthusiasm marker. A lukewarm reference is not thrilled." },
  { phrase: "it is a pleasure", why: "An enthusiasm marker inconsistent with a reserved letter." },
  { phrase: "it is my pleasure", why: "An enthusiasm marker inconsistent with a reserved letter." },
  { phrase: "enthusiastically", why: "An enthusiasm marker inconsistent with a reserved letter." },
  { phrase: "wholeheartedly", why: "An enthusiasm marker inconsistent with a reserved letter." },
  { phrase: "strongly recommend", why: "Overstates a reserved or mixed assessment." },
  { phrase: "highly recommend", why: "Overstates a reserved or mixed assessment." },
  { phrase: "cannot recommend highly enough", why: "Overstates a reserved or mixed assessment." },
  { phrase: "invaluable", why: "Overstates a reserved or mixed assessment." },
  { phrase: "indispensable", why: "Overstates a reserved or mixed assessment." },
  { phrase: "a tremendous asset", why: "Overstates a reserved or mixed assessment." },
  { phrase: "a huge asset", why: "Overstates a reserved or mixed assessment." },
  { phrase: "star performer", why: "Overstates a reserved or mixed assessment." },
];

/**
 * Hedges. Their ABSENCE is the signal, not their presence: a letter declared
 * mixed or reluctant that contains no qualifier anywhere has quietly been
 * rewritten into a warm letter.
 */
const HEDGES = [
  "however",
  "although",
  "though",
  "that said",
  "at times",
  "on occasion",
  "occasionally",
  "sometimes",
  "did struggle",
  "struggled",
  "less confident",
  "less strong",
  "room to grow",
  "room for growth",
  "would benefit from",
  "needs to",
  "not yet",
  "limited",
  "reservation",
  "reservations",
  "caveat",
  "with support",
  "with supervision",
  "in fairness",
  "I cannot speak to",
  "I am not able to speak to",
  "I did not observe",
  "I have not seen",
];

export const BANDS: Record<StrengthBand, BandSpec> = {
  strong: {
    id: "strong",
    label: "Strong — among the best I have worked with",
    rank: 4,
    contract:
      "Confident, specific, evidence-led. Superlatives are permitted ONLY where a listed " +
      "evidence item supports them. A superlative with no evidence behind it is still a fabrication.",
    banned: [],
  },
  solid: {
    id: "solid",
    label: "Solid — clearly good, not exceptional",
    rank: 3,
    contract:
      "Positive but bounded. 'Consistently competent and dependable', not 'exceptional and " +
      "outstanding'. The reader should finish the letter thinking 'good hire', not 'once in a decade'.",
    banned: SUPERLATIVES,
  },
  mixed: {
    id: "mixed",
    label: "Mixed — real strengths, real weaknesses",
    rank: 2,
    contract:
      "Genuinely mixed. Strengths and weaknesses sit side by side and in proportion to what the " +
      "writer reported. Do NOT resolve the mix into an overall positive impression, and do not " +
      "place every weakness in a single sentence at the end where it can be skimmed past.",
    banned: [...SUPERLATIVES, ...ENTHUSIASM],
    expectedHedges: HEDGES,
  },
  reluctant: {
    id: "reluctant",
    label: "Reluctant — I agreed to write this, that is all",
    rank: 1,
    contract:
      "Lukewarm, and it must READ lukewarm to a reader who does not know the writer. Flat, " +
      "factual, hedged. State the reservations plainly in the body. Do not compensate for the " +
      "reservations with warmth elsewhere. The honest failure mode of this band is faint praise, " +
      "not criticism: say what is true and stop.",
    banned: [...SUPERLATIVES, ...ENTHUSIASM],
    expectedHedges: HEDGES,
  },
};

export const BAND_ORDER: StrengthBand[] = ["reluctant", "mixed", "solid", "strong"];

export function bandRank(band: StrengthBand): number {
  return BANDS[band].rank;
}
