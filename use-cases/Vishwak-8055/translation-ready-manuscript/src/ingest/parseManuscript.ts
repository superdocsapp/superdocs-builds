import { createHash } from "node:crypto";
import type { Block, BlockKind, Chapter, InlineSpan, ManuscriptMetadata, ParsedManuscript, SourceLocation } from "../types.js";

/**
 * Parses a plain-text manuscript (Project Gutenberg-style formatting) into
 * structured chapters and blocks.
 *
 * This is deliberately deterministic code, not an LLM call: chapter
 * boundaries, paragraph breaks, italics, and verse layout are things a
 * parser should get right every time, not something we want AI variance on.
 * See Phase 6 of the engineering plan -- deterministic where deterministic
 * code is better.
 *
 * Known limitation, stated rather than hidden: dialogue vs. verse
 * classification below is a heuristic tuned against the Gutenberg plain-text
 * convention (verse lines carry meaningful indentation; dialogue paragraphs
 * are quote-dense). It will misclassify manuscripts formatted very
 * differently from this convention -- see tests/fixtures/second-manuscript.txt
 * for a second, differently-formatted fixture that exercises this.
 */

const CHAPTER_RE = /^(?:#+\s*)?CHAPTER\s+([IVXLCDM]+|\d+)[.\-:\s]*(.*)$/i;
const GUTENBERG_START_RE = /\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^*]*\*\*\*/i;
const GUTENBERG_END_RE = /\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^*]*\*\*\*/i;

export function sourceHashOf(rawSource: string): string {
  return createHash("sha256").update(rawSource, "utf8").digest("hex").slice(0, 16);
}

function slugify(input: string): string {
  return input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 40);
}

/** Strips Gutenberg license header/footer if present. Safe no-op if markers are absent (e.g. an already-trimmed excerpt). */
function stripGutenbergBoilerplate(text: string): string {
  let body = text;
  const startMatch = body.match(GUTENBERG_START_RE);
  if (startMatch && startMatch.index !== undefined) {
    body = body.slice(startMatch.index + startMatch[0].length);
  }
  const endMatch = body.match(GUTENBERG_END_RE);
  if (endMatch && endMatch.index !== undefined) {
    body = body.slice(0, endMatch.index);
  }
  return body.trim();
}

/** Very small, honest heuristic: common-English-stopword density. Returns null rather than guessing when inconclusive. */
function detectSourceLanguageHeuristic(sampleText: string): string | null {
  const words = sampleText.toLowerCase().match(/[a-z']+/g) ?? [];
  if (words.length < 50) return null;
  const stopwords = new Set(["the", "and", "of", "to", "a", "in", "was", "she", "it", "her"]);
  const hits = words.filter((w) => stopwords.has(w)).length;
  const ratio = hits / words.length;
  return ratio > 0.12 ? "English" : null;
}

function extractMetadata(headerText: string, firstChapterSample: string): ManuscriptMetadata {
  const lines = headerText
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0 && l !== "[Illustration]");

  let title: string | null = null;
  let author: string | null = null;
  const provenance: ManuscriptMetadata["provenance"] = {};

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line === undefined) continue;
    const byMatch = line.match(/^by\s+(.+)$/i);
    if (byMatch && title && !author) {
      author = byMatch[1] ?? null;
      provenance.author = { chapterId: "front-matter", chapterTitle: "Front matter", blockIndex: i, evidenceQuote: line };
      continue;
    }
    if (!title && line.toLowerCase() !== "contents" && !/^#+\s*chapter\s/i.test(line) && !/^the\s+\w+\s+edition/i.test(line)) {
      title = line;
      provenance.title = { chapterId: "front-matter", chapterTitle: "Front matter", blockIndex: i, evidenceQuote: line };
    }
  }

  const sourceLanguage = detectSourceLanguageHeuristic(firstChapterSample);
  if (sourceLanguage) {
    provenance.sourceLanguage = {
      chapterId: "front-matter",
      chapterTitle: "Front matter",
      blockIndex: 0,
      evidenceQuote: "(inferred from stopword frequency across the opening chapter)",
    };
  }

  return { title, author, sourceLanguage, provenance };
}

/** Splits `_emphasis_`-marked plain text into inline spans. Gutenberg's plain-text italics convention. */
function parseInlineSpans(rawLine: string): { spans: InlineSpan[]; plainText: string; hasEmphasis: boolean } {
  const spans: InlineSpan[] = [];
  let hasEmphasis = false;
  const re = /_([^_]+)_|\*\*([^*]+)\*\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(rawLine)) !== null) {
    if (match.index > lastIndex) {
      spans.push({ text: rawLine.slice(lastIndex, match.index) });
    }
    const text = match[1] ?? match[2] ?? "";
    spans.push({ text, emphasis: match[1] !== undefined ? "italic" : "bold" });
    hasEmphasis = true;
    lastIndex = re.lastIndex;
  }
  if (lastIndex < rawLine.length) {
    spans.push({ text: rawLine.slice(lastIndex) });
  }
  const plainText = spans.map((s) => s.text).join("");
  return { spans, plainText, hasEmphasis };
}

/**
 * A paragraph is verse if its line breaks look intentional rather than mechanical.
 *
 * Two independent signals, either sufficient on its own:
 *
 *  1. Indentation -- this edition indents alternating lines of some (not all)
 *     of its verse. Cheap and reliable where present.
 *
 *  2. "Next word would still have fit" -- plain-text prose is greedy-wrapped
 *     at a roughly fixed column width, so a hard-wrapped prose line almost
 *     always ends because the *next* word did not fit, not because the
 *     writer chose to stop there. Verse breaks for poetic reasons, so most
 *     lines end with plenty of room left on the row. We estimate the
 *     document's wrap width once (from its longest lines) and then check,
 *     for each non-final line, whether the following line's first word
 *     would have fit within that width. If most lines show slack, the
 *     breaks are intentional.
 *
 * This second signal is what catches the Lobster Quadrille song in the
 * Alice fixture: unlike the other three poems in this edition, it is not
 * indented, so signal 1 alone misses it -- a real formatting inconsistency
 * within a single real source document, not a hypothetical.
 */
export function looksLikeVerse(rawLines: string[], wrapWidth: number): boolean {
  if (rawLines.length < 2) return false;

  const indented = rawLines.filter((l) => /^\s{2,}/.test(l)).length;
  if (indented / rawLines.length >= 0.25) return true;

  let slackCount = 0;
  let applicable = 0;
  for (let i = 0; i < rawLines.length - 1; i++) {
    const line = (rawLines[i] ?? "").trim();
    const nextLine = (rawLines[i + 1] ?? "").trim();
    if (line.length === 0 || nextLine.length === 0) continue;
    const nextFirstWord = nextLine.split(/\s+/)[0] ?? "";
    applicable++;
    // By definition, greedy word-wrapping stops a line exactly when the next
    // word would NOT fit within the wrap width -- that's what "greedy" means.
    // So for genuinely mechanical prose wrapping this condition should
    // essentially never be true; no safety margin needed once wrapWidth
    // itself is measured accurately (see estimateWrapWidth).
    if (line.length + 1 + nextFirstWord.length <= wrapWidth) {
      slackCount++;
    }
  }
  if (applicable === 0) return false;
  return slackCount / applicable >= 0.7;
}

/** Estimates the manuscript's mechanical line-wrap width from its longest lines, so looksLikeVerse has a baseline to compare against. */
export function estimateWrapWidth(body: string): number {
  const lengths = body
    .split("\n")
    .map((l) => l.trimEnd().length)
    .filter((len) => len > 0)
    .sort((a, b) => a - b);
  if (lengths.length === 0) return 72;
  const p95Index = Math.floor(lengths.length * 0.95);
  return Math.max(lengths[p95Index] ?? 72, 60);
}

/** A paragraph is dialogue-classified if quoted speech accounts for a large share of its characters. A heuristic, not a guarantee -- see file header. */
function looksLikeDialogue(text: string): boolean {
  const quoted = text.match(/[\u201C"][^\u201D"]*[\u201D"]/g) ?? [];
  const quotedChars = quoted.reduce((sum, q) => sum + q.length, 0);
  return text.length > 0 && quotedChars / text.length > 0.4;
}

function buildBlock(id: string, kind: BlockKind, rawLines: string[]): Block {
  if (kind === "verse") {
    // Preserve line breaks: join with a marker newline so downstream consumers (packet/export) can render stanza structure.
    const joined = rawLines.map((l) => l.trim()).join("\n");
    const { spans, plainText, hasEmphasis } = parseInlineSpans(joined);
    return { id, kind, text: plainText, spans, hasEmphasis };
  }
  const joined = rawLines.map((l) => l.trim()).join(" ").replace(/\s+/g, " ").trim();
  const { spans, plainText, hasEmphasis } = parseInlineSpans(joined);
  const kindResolved: BlockKind = kind === "paragraph" && looksLikeDialogue(plainText) ? "dialogue" : kind;
  return { id, kind: kindResolved, text: plainText, spans, hasEmphasis };
}

function splitIntoRawParagraphs(chapterBody: string): string[][] {
  const lines = chapterBody.split("\n");
  const paragraphs: string[][] = [];
  let current: string[] = [];
  for (const line of lines) {
    if (line.trim() === "" || /^\*\s*\*\s*\*/.test(line.trim())) {
      if (current.length > 0) {
        paragraphs.push(current);
        current = [];
      }
      continue;
    }
    current.push(line);
  }
  if (current.length > 0) paragraphs.push(current);
  return paragraphs;
}

export interface ParseManuscriptOptions {
  sourceFilename?: string;
  sourceFormat?: string;
}

export function parseManuscript(rawSourceInput: string, options: ParseManuscriptOptions = {}): ParsedManuscript {
  const rawSource = rawSourceInput;
  const body = stripGutenbergBoilerplate(rawSourceInput);

  const lines = body.split("\n");
  const chapterStarts: { lineIndex: number; title: string }[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line === undefined) continue;
    const chapterMatch = line.trim().match(CHAPTER_RE);
    if (chapterMatch) {
      const inlineTitle = (chapterMatch[2] ?? "").trim();
      const previousIsChapter = i > 0 && CHAPTER_RE.test((lines[i - 1] ?? "").trim());
      const nextIsChapter = i + 1 < lines.length && CHAPTER_RE.test((lines[i + 1] ?? "").trim());
      // A run of inline "CHAPTER I. Title" lines is normally a table of contents.
      // Real chapter headings in this parser are followed by body text or put the
      // title on the next line. Skipping the consecutive run prevents TOC entries
      // from becoming duplicate chapters while still accepting inline headings in
      // ordinary documents.
      if (inlineTitle && (previousIsChapter || nextIsChapter)) continue;

      let title = inlineTitle;
      if (!title) {
        // Title is the next non-blank line for Gutenberg-style "CHAPTER I."
        // If the next paragraph looks like prose rather than a heading, keep a
        // stable generic chapter title and do not consume that paragraph.
        let j = i + 1;
        while (j < lines.length && lines[j]?.trim() === "") j++;
        const candidate = (lines[j] ?? "").trim();
        const looksLikeHeading = candidate.length > 0 && candidate.length <= 100 && !/[.!?;:]$/.test(candidate);
        title = looksLikeHeading ? candidate : `Chapter ${chapterMatch[1]}`;
      }
      if (title) chapterStarts.push({ lineIndex: i, title });
    }
  }

  const wrapWidth = estimateWrapWidth(body);

  const headerText = lines.slice(0, chapterStarts[0]?.lineIndex ?? lines.length).join("\n");
  const firstChapterBodyForLangDetect = chapterStarts.length
    ? lines.slice(chapterStarts[0]!.lineIndex, chapterStarts[1]?.lineIndex ?? lines.length).join("\n")
    : body;
  const metadata = { ...extractMetadata(headerText, firstChapterBodyForLangDetect), sourceFilename: options.sourceFilename, sourceFormat: options.sourceFormat };

  const chapters: Chapter[] = chapterStarts.map((start, idx) => {
    const bodyStartLine = start.lineIndex + 1;
    const bodyEndLine = chapterStarts[idx + 1]?.lineIndex ?? lines.length;
    // Skip the title line itself (it repeats within the first couple of lines of the body).
    let contentStart = bodyStartLine;
    let skipped = 0;
    while (contentStart < bodyEndLine && skipped < 3) {
      const t = lines[contentStart]?.trim() ?? "";
      if (t === "" || t === start.title) {
        contentStart++;
        skipped++;
        continue;
      }
      break;
    }
    const chapterBody = lines.slice(contentStart, bodyEndLine).join("\n");
    const chapterId = `ch${String(idx + 1).padStart(2, "0")}-${slugify(start.title)}`;

    const rawParagraphs = splitIntoRawParagraphs(chapterBody);
    const blocks: Block[] = rawParagraphs.map((rawLines, bIdx) => {
      const kind: BlockKind = looksLikeVerse(rawLines, wrapWidth) ? "verse" : "paragraph";
      return buildBlock(`${chapterId}-b${bIdx}`, kind, rawLines);
    });

    return { id: chapterId, index: idx + 1, title: start.title, blocks };
  });

  return {
    metadata,
    chapters,
    rawSource,
    sourceHash: sourceHashOf(rawSource),
  };
}

export function locationOf(chapter: Chapter, blockIndex: number, evidenceQuote: string): SourceLocation {
  return { chapterId: chapter.id, chapterTitle: chapter.title, blockIndex, evidenceQuote };
}
