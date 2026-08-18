import type {
  Chapter,
  DoNotTranslateRule,
  FormattingRule,
  ParsedManuscript,
  StyleNote,
  TermCandidate,
  TranslationPacket,
} from "../types.js";

/**
 * Builds the translation-ready packet: clean source + term base + do-not-
 * translate rules + style note + formatting guidance. This is the actual
 * handoff artifact -- a translator should be able to work from this without
 * repeatedly asking "what does this term mean" or "should this stay
 * italic."
 *
 * Deliberately takes the FULL term candidate list (any status), not just
 * confirmed ones: a translator benefits from seeing suggested terms too
 * (clearly marked as unreviewed) rather than losing that information
 * because nobody had gotten to review it yet. Only confirmed terms produce
 * enforceable do-not-translate rules -- see rules/protectedTerms.ts.
 */

function renderCleanSourceHtml(manuscript: ParsedManuscript): string {
  const parts: string[] = [];
  if (manuscript.metadata.title) parts.push(`<h1 data-chunk-id="title">${escapeHtml(manuscript.metadata.title)}</h1>`);
  if (manuscript.metadata.author) parts.push(`<p data-chunk-id="author" class="author">${escapeHtml(manuscript.metadata.author)}</p>`);

  for (const chapter of manuscript.chapters) {
    parts.push(`<h2 data-chunk-id="${chapter.id}-heading">${escapeHtml(chapter.title)}</h2>`);
    chapter.blocks.forEach((block, i) => {
      const chunkId = `${chapter.id}-b${i}`;
      const inner = block.spans.length
        ? block.spans.map((s) => (s.emphasis === "italic" ? `<em>${escapeHtml(s.text)}</em>` : s.emphasis === "bold" ? `<strong>${escapeHtml(s.text)}</strong>` : escapeHtml(s.text))).join("")
        : escapeHtml(block.text);
      if (block.kind === "verse") {
        const lines = inner.split("\n").map((l) => l);
        parts.push(`<p data-chunk-id="${chunkId}" class="verse">${lines.join("<br/>")}</p>`);
      } else {
        const tag = block.kind === "dialogue" ? "p" : "p";
        const cls = block.kind === "dialogue" ? ' class="dialogue"' : "";
        parts.push(`<${tag} data-chunk-id="${chunkId}"${cls}>${inner}</${tag}>`);
      }
    });
  }
  return parts.join("\n");
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** Formatting rules for every block that carries emphasis -- "preserve italics, they carry meaning" made concrete and per-location rather than a generic instruction. */
function buildFormattingGuidance(chapters: Chapter[]): FormattingRule[] {
  const rules: FormattingRule[] = [];
  let seq = 0;
  for (const chapter of chapters) {
    rules.push({
      id: `fmt-${seq++}`,
      source: { chapterId: chapter.id, chapterTitle: chapter.title, blockIndex: -1, evidenceQuote: chapter.title },
      formatting: "heading",
      meaning: "Chapter heading establishes structural hierarchy and navigation.",
      translationRequirement: "Preserve chapter-heading hierarchy and numbering; translate the heading text without flattening it into body prose.",
    });
    chapter.blocks.forEach((block, i) => {
      if (block.hasEmphasis) {
        const emphasizedSpans = block.spans.filter((s) => s.emphasis === "italic").map((s) => s.text);
        if (emphasizedSpans.length) {
          rules.push({
            id: `fmt-${seq++}`,
            source: { chapterId: chapter.id, chapterTitle: chapter.title, blockIndex: i, evidenceQuote: block.text.slice(0, 100) },
            formatting: "italic",
            meaning: `Emphasizes: ${emphasizedSpans.map((t) => `"${t}"`).join(", ")}`,
            translationRequirement: "Preserve italic formatting on the emphasized word(s); emphasis is meaningful, not decorative.",
          });
        }
        const boldSpans = block.spans.filter((s) => s.emphasis === "bold").map((s) => s.text);
        if (boldSpans.length) {
          rules.push({
            id: `fmt-${seq++}`,
            source: { chapterId: chapter.id, chapterTitle: chapter.title, blockIndex: i, evidenceQuote: block.text.slice(0, 100) },
            formatting: "bold",
            meaning: `Emphasizes: ${boldSpans.map((t) => `"${t}"`).join(", ")}`,
            translationRequirement: "Preserve bold formatting where it carries emphasis, hierarchy or document semantics.",
          });
        }
      }
      if (block.kind === "dialogue") {
        rules.push({
          id: `fmt-${seq++}`,
          source: { chapterId: chapter.id, chapterTitle: chapter.title, blockIndex: i, evidenceQuote: block.text.slice(0, 100) },
          formatting: "dialogue_structure",
          meaning: "This block is dialogue and contributes to speaker rhythm and scene structure.",
          translationRequirement: "Preserve dialogue as dialogue and retain speaker intent, turn-taking and punctuation conventions.",
        });
      }
      if (block.kind === "verse") {
        rules.push({
          id: `fmt-${seq++}`,
          source: { chapterId: chapter.id, chapterTitle: chapter.title, blockIndex: i, evidenceQuote: block.text.slice(0, 60) },
          formatting: "verse_structure",
          meaning: "This block is verse; line breaks are the poet's, not incidental wrapping.",
          translationRequirement: "Preserve line-break structure. A translated stanza does not need the same line count, but should remain verse, not be reflowed into prose.",
        });
      }
    });
  }
  return rules;
}

export interface BuildPacketInput {
  manuscript: ParsedManuscript;
  allTerms: TermCandidate[];
  confirmedRules: DoNotTranslateRule[];
  styleNote: StyleNote;
  targetLanguage: string;
  targetLocale?: string;
}

export function buildTranslationPacket(input: BuildPacketInput): TranslationPacket {
  return {
    manuscriptTitle: input.manuscript.metadata.title ?? "(untitled manuscript)",
    targetLanguage: input.targetLanguage,
    targetLocale: input.targetLocale,
    cleanSourceHtml: renderCleanSourceHtml(input.manuscript),
    termBase: input.allTerms,
    doNotTranslateRules: input.confirmedRules,
    styleNote: input.styleNote,
    formattingGuidance: buildFormattingGuidance(input.manuscript.chapters),
    sourceMetadata: {
      filename: input.manuscript.metadata.sourceFilename ?? null,
      format: input.manuscript.metadata.sourceFormat ?? null,
      author: input.manuscript.metadata.author,
      sourceLanguage: input.manuscript.metadata.sourceLanguage,
    },
    generatedAt: new Date().toISOString(),
    sourceHash: input.manuscript.sourceHash,
  };
}
