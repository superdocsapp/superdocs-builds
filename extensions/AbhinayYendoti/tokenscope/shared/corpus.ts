import type { DocumentSnapshot } from "./types.js";

/**
 * The benchmark corpus.
 *
 * The point of the benchmark is that the gap between a surgical edit and a
 * whole-document regeneration widens with document size, so the only thing that
 * may vary between runs is the size. Everything else - the prose, the section
 * structure, the paragraph that gets edited, the instruction - is fixed.
 *
 * The generator is deterministic: same size in, byte-identical document out, on
 * any machine, with no network and no stored fixture. Re-running the benchmark
 * measures the API again, never a different document.
 */

/** A "page" here is 500 words of body text. Stated so the table means something. */
export const WORDS_PER_PAGE = 500;

export const BENCHMARK_SIZES = [3, 10, 50, 100, 300] as const;

export type BenchmarkSize = (typeof BENCHMARK_SIZES)[number];

/**
 * The paragraph every run edits, and the only paragraph any run edits.
 *
 * It is deliberately overwritten prose: verbose enough that "make this more
 * concise" is a real instruction with a checkable outcome, and distinctive
 * enough that it can be located in a 300-page document by exact match.
 */
export const TARGET_PARAGRAPH =
  "Notwithstanding any provision of this agreement to the contrary, it should be noted " +
  "that the parties hereto have, over the course of the period under review, undertaken " +
  "a not insubstantial number of separate and distinct initiatives which, when taken " +
  "together and considered in the aggregate rather than in isolation, may fairly be said " +
  "to have contributed in a material and demonstrable fashion to the overall operating " +
  "performance of the organisation considered as a whole.";

export const INSTRUCTION = "Make this more concise.";

/** Deterministic PRNG (mulberry32). Seeded per document, never per process. */
function rng(seed: number): () => number {
  let a = seed >>> 0;

  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const SUBJECTS = [
  "the operating committee",
  "the regional finance team",
  "the platform engineering group",
  "the supplier review board",
  "the internal audit function",
  "the customer success organisation"
];

const VERBS = [
  "reviewed",
  "reconciled",
  "escalated",
  "approved",
  "deferred",
  "documented",
  "re-scoped"
];

const OBJECTS = [
  "the quarterly variance report",
  "the outstanding accrual schedule",
  "the third-party integration backlog",
  "the revised service credit model",
  "the data retention exceptions",
  "the capital expenditure forecast"
];

const CLAUSES = [
  "ahead of the reporting deadline",
  "without material change to the underlying assumptions",
  "subject to confirmation from the external auditor",
  "in line with the policy agreed at the start of the period",
  "with one exception carried forward to the next cycle",
  "and recorded the outcome in the control log"
];

function pick<T>(items: readonly T[], next: () => number): T {
  return items[Math.floor(next() * items.length)] as T;
}

function sentence(next: () => number): string {
  const subject = pick(SUBJECTS, next);
  const head = subject.charAt(0).toUpperCase() + subject.slice(1);
  return `${head} ${pick(VERBS, next)} ${pick(OBJECTS, next)} ${pick(CLAUSES, next)}.`;
}

/**
 * Build a document of roughly `pages` pages.
 *
 * The target paragraph is placed just past the middle, so the model cannot reach
 * it by reading only the beginning of the document.
 */
export function buildDocument(pages: number): DocumentSnapshot {
  const next = rng(0x7c0e5c09 + pages);
  const targetWords = pages * WORDS_PER_PAGE;

  const body: string[] = [];
  let words = 0;
  let section = 1;

  while (words < targetWords) {
    body.push(`Section ${section}. Operating review`);
    words += 4;

    const paragraphs = 3 + Math.floor(next() * 3);

    for (let p = 0; p < paragraphs && words < targetWords; p += 1) {
      const sentences: string[] = [];

      for (let s = 0; s < 4 + Math.floor(next() * 3); s += 1) sentences.push(sentence(next));

      const text = sentences.join(" ");
      body.push(text);
      words += text.split(/\s+/u).length;
    }

    section += 1;
  }

  // Just past the middle: far enough in that reaching it means reading the document.
  body.splice(Math.floor(body.length * 0.55), 0, TARGET_PARAGRAPH);

  const paragraphs = [`Operating Review - ${pages} page reference document`, ...body].map(
    (text, index) => ({ id: `p${index}`, text })
  );

  return { paragraphs };
}

export function wordCount(document: DocumentSnapshot): number {
  return document.paragraphs.reduce((sum, p) => sum + p.text.split(/\s+/u).length, 0);
}
