/**
 * The editorial passes — the only place this plugin spends money.
 *
 * Compiling a manuscript is a typesetting problem and is solved deterministically
 * offline. What a model is genuinely good at is the writing around the writing:
 * a jacket blurb, a preface draft, an honest read on whether chapter nine's voice
 * has drifted. Those are the passes offered here, each one:
 *
 *   - opt-in, never automatic
 *   - costed up front, with the operation count stated before it runs
 *   - scoped to a slice of the manuscript rather than the whole 300 pages
 *   - reviewed change by change before anything is written back
 *
 * The scoping matters for more than money. Sending 300 pages to ask for a 200-word
 * blurb is slow, expensive, and gives a worse blurb than sending the parts that
 * actually decide it.
 */

import { buildInstruction } from "../core/injection";
import type { CompileResult } from "../core/types";
import { stripTags } from "../core/util";

export type PassId =
  | "front-matter"
  | "blurb"
  | "voice-check"
  | "chapter-polish"
  | "synopsis"
  | "custom";

export interface EditorialPass {
  id: PassId;
  title: string;
  /** One line, shown in the command palette and the confirm dialog. */
  description: string;
  /** How many SuperDocs operations one run costs, at the current scoping. */
  estimatedOperations: number;
  /** Whether the pass edits the manuscript or only reports back. */
  writes: boolean;
}

export const PASSES: Record<PassId, EditorialPass> = {
  "front-matter": {
    id: "front-matter",
    title: "Draft the preface",
    description:
      "Reads the chapter titles and openings and drafts a preface in the book's own voice.",
    estimatedOperations: 1,
    writes: true,
  },
  blurb: {
    id: "blurb",
    title: "Write a jacket blurb",
    description: "Produces a 150–200 word back-cover blurb from the synopsis material.",
    estimatedOperations: 1,
    writes: true,
  },
  "voice-check": {
    id: "voice-check",
    title: "Check voice consistency",
    description:
      "Reports where tense, person or register drift between chapters. Reports only; changes nothing.",
    estimatedOperations: 1,
    writes: false,
  },
  "chapter-polish": {
    id: "chapter-polish",
    title: "Polish one chapter",
    description: "Line-edits a single chapter you choose. Every change is reviewed individually.",
    estimatedOperations: 1,
    writes: true,
  },
  synopsis: {
    id: "synopsis",
    title: "Build a chapter synopsis",
    description: "One paragraph per chapter, for an agent or a commissioning editor.",
    estimatedOperations: 1,
    writes: true,
  },
  custom: {
    id: "custom",
    title: "Custom instruction",
    description: "Send your own instruction against the scoped manuscript.",
    estimatedOperations: 1,
    writes: true,
  },
};

export interface PassRequest {
  pass: PassId;
  /** The manuscript, already compiled. */
  compiled: CompileResult;
  /** Full chapter HTML, in spine order, for scoping. */
  chapterHtml: string[];
  /** For chapter-polish: which spine index to work on. */
  chapterIndex?: number;
  /** For custom: the user's instruction. */
  customInstruction?: string;
  /** Hard cap on characters sent, so a 300-page book cannot blow up one request. */
  maxChars?: number;
}

export interface PassPlan {
  /** The document HTML to send. Never the whole book unless the pass needs it. */
  documentHtml: string;
  /** The instruction, wrapped in the content-boundary envelope. */
  instruction: string;
  /** True when the pass proposes edits that must be reviewed. */
  writes: boolean;
  /** Characters actually sent, for the cost preview. */
  chars: number;
  /** Plain-language description of what was sent, shown before the user confirms. */
  scopeDescription: string;
  estimatedOperations: number;
}

const DEFAULT_MAX_CHARS = 120_000;

/**
 * Build the request without sending it.
 *
 * Separating "what would this cost and what would it see" from "do it" is the
 * no-spend preview the free tier makes essential: 500 operations a month does not
 * survive a loop that discovers its own scope at runtime.
 */
export function planPass(req: PassRequest): PassPlan {
  const maxChars = req.maxChars ?? DEFAULT_MAX_CHARS;
  const meta = req.compiled.meta;
  const titleLine = `${meta.title}${meta.subtitle ? `: ${meta.subtitle}` : ""}${
    meta.author ? `, by ${meta.author}` : ""
  }`;

  switch (req.pass) {
    case "front-matter": {
      const openings = req.compiled.spine
        .map((entry, i) => {
          const text = stripTags(req.chapterHtml[i] ?? "").slice(0, 600);
          return `<section data-chapter="${i + 1}"><h2>${escape(entry.title)}</h2><p>${escape(
            text,
          )}</p></section>`;
        })
        .join("\n");
      return {
        documentHtml: clamp(`<h1>${escape(titleLine)}</h1>\n${openings}`, maxChars),
        instruction: buildInstruction(
          "Write a preface of 400 to 600 words for this book, in the same voice as the chapter " +
            "openings you can see. Put it at the top of the document under the heading 'Preface'. " +
            "Do not invent facts, events or sources that the chapter openings do not support; " +
            "where you would need a fact you do not have, write around it instead.",
        ),
        writes: true,
        chars: 0,
        scopeDescription: `the title and the first ~600 characters of each of ${req.compiled.spine.length} chapters`,
        estimatedOperations: 1,
      };
    }

    case "blurb": {
      const first = stripTags(req.chapterHtml[0] ?? "").slice(0, 3000);
      const last = stripTags(req.chapterHtml[req.chapterHtml.length - 1] ?? "").slice(0, 1500);
      return {
        documentHtml: clamp(
          `<h1>${escape(titleLine)}</h1><h2>Opening</h2><p>${escape(
            first,
          )}</p><h2>Close</h2><p>${escape(last)}</p>`,
          maxChars,
        ),
        instruction: buildInstruction(
          "Write a back-cover blurb of 150 to 200 words for this book, under the heading " +
            "'Back Cover'. Sell the book honestly: no claims about awards, reviews, sales or " +
            "endorsements, because none exist. If the material does not support a claim, leave it out.",
        ),
        writes: true,
        chars: 0,
        scopeDescription: "the opening of the first chapter and the close of the last",
        estimatedOperations: 1,
      };
    }

    case "voice-check": {
      const samples = req.compiled.spine
        .map((entry, i) => {
          const text = stripTags(req.chapterHtml[i] ?? "");
          const sample = text.slice(0, 900);
          return `<section><h2>${escape(entry.title)}</h2><p>${escape(sample)}</p></section>`;
        })
        .join("\n");
      return {
        documentHtml: clamp(samples, maxChars),
        instruction: buildInstruction(
          "Read these chapter samples and report, as a list under the heading 'Voice Report', " +
            "every place where tense, narrative person, or register is inconsistent between " +
            "chapters. Name the chapter and quote the phrase. Change nothing else in the " +
            "document. If the samples are consistent, say so plainly and list nothing.",
        ),
        writes: false,
        chars: 0,
        scopeDescription: `a ~900 character sample from each of ${req.compiled.spine.length} chapters`,
        estimatedOperations: 1,
      };
    }

    case "chapter-polish": {
      const index = req.chapterIndex ?? 0;
      const html = req.chapterHtml[index] ?? "";
      const entry = req.compiled.spine[index];
      return {
        documentHtml: clamp(html, maxChars),
        instruction: buildInstruction(
          "Line-edit this chapter for clarity and rhythm. Keep the author's voice, keep every " +
            "figure, footnote marker and citation exactly where it is, and do not change any " +
            "heading text. Propose each edit separately so it can be accepted or rejected on " +
            "its own.",
        ),
        writes: true,
        chars: 0,
        scopeDescription: `one chapter: ${entry?.title ?? `#${index + 1}`}`,
        estimatedOperations: 1,
      };
    }

    case "synopsis": {
      const bodies = req.compiled.spine
        .map((entry, i) => {
          const text = stripTags(req.chapterHtml[i] ?? "").slice(0, 1200);
          return `<section><h2>${escape(entry.title)}</h2><p>${escape(text)}</p></section>`;
        })
        .join("\n");
      return {
        documentHtml: clamp(bodies, maxChars),
        instruction: buildInstruction(
          "Write a chapter-by-chapter synopsis under the heading 'Synopsis': one paragraph per " +
            "chapter, in the order given, each naming what actually happens in it. Base every " +
            "paragraph only on the text you can see; if a chapter's sample is too short to " +
            "summarise, say that instead of guessing.",
        ),
        writes: true,
        chars: 0,
        scopeDescription: `the first ~1200 characters of each of ${req.compiled.spine.length} chapters`,
        estimatedOperations: 1,
      };
    }

    case "custom":
    default: {
      const joined = req.chapterHtml.join("\n");
      return {
        documentHtml: clamp(joined, maxChars),
        instruction: buildInstruction(req.customInstruction ?? "Improve this document."),
        writes: true,
        chars: 0,
        scopeDescription:
          joined.length > maxChars
            ? `the first ${maxChars.toLocaleString()} characters of the manuscript (it was truncated to keep the request affordable)`
            : "the whole manuscript body",
        estimatedOperations: 1,
      };
    }
  }
}

/** Fill in the character count after the plan is built. */
export function finalisePlan(plan: PassPlan): PassPlan {
  return { ...plan, chars: plan.documentHtml.length };
}

function clamp(html: string, maxChars: number): string {
  if (html.length <= maxChars) return html;
  return `${html.slice(0, maxChars)}\n<!-- truncated at ${maxChars} characters -->`;
}

function escape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
