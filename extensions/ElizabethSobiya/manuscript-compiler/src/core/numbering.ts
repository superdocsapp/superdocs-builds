/**
 * Assembly-time numbering.
 *
 * Every chapter arrives with tokens where numbers belong. This pass walks the
 * chapters in spine order, assigns figure numbers, footnote numbers and citation
 * numbers once, and resolves every token.
 *
 * Two guarantees this pass owns:
 *   - Numbering is continuous across chapter boundaries. Figure 12 in chapter 9
 *     follows figure 11 in chapter 8, and footnote 214 follows footnote 213.
 *   - Nothing is invented. A cross-reference to a figure that no chapter placed,
 *     or a citation key with no bibliography entry, resolves to a visible marker
 *     and a diagnostic — never to a plausible-looking number.
 */

import type { BibDatabase } from "./bibtex";
import { renderCitationGroup } from "./citations";
import type {
  CitationRef,
  CitationStyle,
  Diagnostic,
  FigureNumbering,
  RenderedChapter,
} from "./types";
import { resolveTokens, type Token } from "./tokens";
import { escapeAttr, escapeHtml } from "./util";
import { footnoteId } from "./render";

export interface NumberingOptions {
  figureNumbering: FigureNumbering;
  citationStyle: CitationStyle;
  bib: BibDatabase | null;
}

export interface AssignedFigure {
  key: string;
  label: string;
  caption: string;
  sourcePath: string | null;
  chapterOrder: number;
  anchor: string;
}

export interface AssignedFootnote {
  key: string;
  number: number;
  html: string;
  chapterOrder: number;
}

export interface NumberingResult {
  /** Chapter HTML with every token resolved, in spine order. */
  chapters: string[];
  figures: AssignedFigure[];
  footnotes: AssignedFootnote[];
  /** Cite keys in order of first appearance — the numeric-style ordering. */
  citationOrder: string[];
  diagnostics: Diagnostic[];
}

function parseCiteToken(payload: string): CitationRef[] {
  return payload.split("~").map((part) => {
    let s = part;
    const suppressAuthor = s.startsWith("-");
    if (suppressAuthor) s = s.slice(1);
    const narrative = s.startsWith(">");
    if (narrative) s = s.slice(1);
    const bar = s.indexOf("|");
    return {
      citeKey: bar >= 0 ? s.slice(0, bar) : s,
      locator: bar >= 0 ? s.slice(bar + 1) : null,
      suppressAuthor,
      narrative,
    };
  });
}

export function assignNumbers(
  chapters: RenderedChapter[],
  opts: NumberingOptions,
): NumberingResult {
  const diagnostics: Diagnostic[] = [];

  // --- Pass 1: assign numbers ------------------------------------------------
  const figures: AssignedFigure[] = [];
  const figureLabel = new Map<string, string>();
  const footnotes: AssignedFootnote[] = [];
  const footnoteNumber = new Map<string, number>();
  const citationNumbers = new Map<string, number>();
  const citationOrder: string[] = [];
  let footnoteCounter = 0;

  // Figure numbering.
  //   by-chapter: "Figure 3.1" — 3 is the body chapter's ordinal (whether or not
  //     earlier chapters had figures), 1 restarts inside each top-level chapter.
  //     Nested sub-chapters continue their parent chapter's sequence.
  //     Figures outside the body (front/back matter) fall back to a continuous
  //     "Figure N" series, because "Figure 0.1" would be a lie about structure.
  //   continuous: one "Figure N" series across the whole manuscript.
  let bodyChapterNumber = 0;
  let withinChapter = 0;
  let continuousCounter = 0;

  for (const ch of chapters) {
    const topLevel = !ch.entry.nested;
    if (ch.entry.region === "body" && topLevel) {
      bodyChapterNumber += 1;
      withinChapter = 0;
    }

    for (const fig of ch.figures) {
      continuousCounter += 1;
      const useChapterForm =
        opts.figureNumbering === "by-chapter" &&
        ch.entry.region === "body" &&
        bodyChapterNumber > 0;
      let label: string;
      if (useChapterForm) {
        withinChapter += 1;
        label = `Figure ${bodyChapterNumber}.${withinChapter}`;
      } else {
        label = `Figure ${continuousCounter}`;
      }
      if (figureLabel.has(fig.key)) {
        diagnostics.push({
          severity: "warning",
          code: "figure.duplicate_key",
          message: `Two figures resolve to the same key "${fig.key}". Cross-references to it point at the first. Rename one of the image files.`,
          file: ch.entry.path,
        });
        continue;
      }
      figureLabel.set(fig.key, label);
      figures.push({
        key: fig.key,
        label,
        caption: fig.caption,
        sourcePath: fig.sourcePath,
        chapterOrder: ch.entry.order,
        anchor: `fig-${fig.key}`,
      });
    }

    for (const fn of ch.footnotes) {
      footnoteCounter += 1;
      footnoteNumber.set(fn.key, footnoteCounter);
      footnotes.push({
        key: fn.key,
        number: footnoteCounter,
        html: fn.html,
        chapterOrder: ch.entry.order,
      });
    }

    for (const cite of ch.citations) {
      if (!citationNumbers.has(cite.citeKey)) {
        citationNumbers.set(cite.citeKey, citationNumbers.size + 1);
        citationOrder.push(cite.citeKey);
      }
    }
  }

  // --- Pass 2: resolve tokens ------------------------------------------------
  const citeCtx = {
    style: opts.citationStyle,
    bib: opts.bib,
    numberFor: (key: string) => citationNumbers.get(key) ?? 0,
    anchorFor: (key: string) =>
      opts.bib?.entries.has(key) ? `bib-${escapeAttr(key)}` : null,
  };

  const reportedMissingCites = new Set<string>();
  const reportedMissingFigs = new Set<string>();

  const resolveIn = (ch: RenderedChapter) => (t: Token): string => {
    switch (t.kind) {
      case "fig": {
        return escapeHtml(figureLabel.get(t.payload) ?? "Figure ?");
      }
      case "figref": {
        const label = figureLabel.get(t.payload);
        if (!label) {
          if (!reportedMissingFigs.has(t.payload)) {
            reportedMissingFigs.add(t.payload);
            diagnostics.push({
              severity: "error",
              code: "figure.unresolved_reference",
              message: `A cross-reference points at the figure "${t.payload}", but no chapter places that image. The reference was left visible rather than given a made-up number.`,
              file: ch.entry.path,
            });
          }
          return `<span class="mc-unresolved">[? figure ${escapeHtml(t.payload)}]</span>`;
        }
        return escapeHtml(label);
      }
      case "fn": {
        const n = footnoteNumber.get(t.payload);
        return n === undefined ? "?" : String(n);
      }
      case "fnbody": {
        const n = footnoteNumber.get(t.payload);
        return n === undefined ? "?" : String(n);
      }
      case "cite": {
        const refs = parseCiteToken(t.payload);
        for (const r of refs) {
          if (opts.bib && !opts.bib.entries.has(r.citeKey) && !reportedMissingCites.has(r.citeKey)) {
            reportedMissingCites.add(r.citeKey);
            diagnostics.push({
              severity: "error",
              code: "citation.unresolved",
              message: `Citation key "${r.citeKey}" has no entry in the bibliography. It is printed as [? ${r.citeKey}] so the gap is visible in the proof.`,
              file: ch.entry.path,
            });
          } else if (!opts.bib && !reportedMissingCites.has(r.citeKey)) {
            reportedMissingCites.add(r.citeKey);
            diagnostics.push({
              severity: "warning",
              code: "citation.no_bibliography",
              message: `This manuscript cites "${r.citeKey}" but no bibliography file is configured, so no citation can be resolved. Set "bibliography:" in the spine's frontmatter.`,
              file: ch.entry.path,
            });
          }
        }
        return renderCitationGroup(refs, citeCtx);
      }
      case "secref":
        return escapeHtml(t.payload);
      default:
        return "";
    }
  };

  const resolvedChapters = chapters.map((ch) => resolveTokens(ch.html, resolveIn(ch)));

  // Footnote bodies carry tokens too — a footnote is exactly where a citation
  // tends to live — and they are assembled separately from the chapter HTML, so
  // they need their own resolve pass or every citation inside a note stays raw.
  const chapterByOrder = new Map(chapters.map((ch) => [ch.entry.order, ch]));
  const resolvedFootnotes = footnotes.map((fn) => {
    const owner = chapterByOrder.get(fn.chapterOrder) ?? chapters[0];
    return owner ? { ...fn, html: resolveTokens(fn.html, resolveIn(owner)) } : fn;
  });

  return {
    chapters: resolvedChapters,
    figures,
    footnotes: resolvedFootnotes,
    citationOrder,
    diagnostics,
  };
}

/**
 * Footnote bodies, in SuperDocs' out-of-flow part shape.
 *
 * Verified against the export pipeline: `<sup data-footnote-ref="fn-x">` plus an
 * `<aside data-part-type="footnote" data-part-id="fn-x">` becomes a real Word
 * footnote in the .docx and a real page-foot note in the PDF. The body text must
 * NOT carry its own "1." prefix — Word numbers footnotes itself, and a manual
 * prefix prints twice.
 */
export function renderFootnoteParts(footnotes: AssignedFootnote[]): string {
  if (footnotes.length === 0) return "";
  return footnotes
    .map(
      (fn) =>
        `<aside data-part-type="footnote" data-part-id="fn-${escapeAttr(
          footnoteId(fn.key),
        )}" role="doc-footnote">${fn.html || "<p></p>"}</aside>`,
    )
    .join("\n");
}

/** Footnotes gathered as a visible back-matter "Notes" section instead. */
export function renderEndnoteSection(
  footnotes: AssignedFootnote[],
  chapterTitles: Map<number, string>,
): string {
  if (footnotes.length === 0) return "";
  const rows: string[] = [];
  let currentChapter = -1;
  for (const fn of footnotes) {
    if (fn.chapterOrder !== currentChapter) {
      if (currentChapter !== -1) rows.push("</ol>");
      currentChapter = fn.chapterOrder;
      rows.push(
        `<h2 class="notes-chapter">${escapeHtml(
          chapterTitles.get(fn.chapterOrder) ?? "Notes",
        )}</h2>`,
      );
      rows.push(`<ol class="endnotes" start="${fn.number}">`);
    }
    rows.push(
      `<li id="fn-${escapeAttr(footnoteId(fn.key))}" value="${fn.number}">${fn.html}</li>`,
    );
  }
  rows.push("</ol>");
  return rows.join("\n");
}
