/**
 * Generated front and back matter.
 *
 * These pages are produced from the spine's metadata, deterministically and with
 * no model involved. A title page is a layout problem, not a writing problem, and
 * spending an AI operation on one would be spending money to get less repeatable
 * output. The editorial passes that *do* call SuperDocs (a preface draft, a jacket
 * blurb, a voice pass) are separate, opt-in, and reviewed — see superdocs/editorial.ts.
 */

import type { AssignedFigure } from "./numbering";
import type { BibDatabase } from "./bibtex";
import { bibSortKey, renderBibEntry } from "./citations";
import type { CitationStyle, HeadingRef, ManuscriptMeta } from "./types";
import { escapeAttr, escapeHtml } from "./util";

/** SuperDocs' page-break marker. Verified: becomes a real Word/PDF page break. */
export const PAGE_BREAK = '<hr data-page-break="true">';

export function titlePage(meta: ManuscriptMeta): string {
  const rows: string[] = [`<h1 class="book-title" id="mc-title-page">${escapeHtml(meta.title)}</h1>`];
  if (meta.subtitle) rows.push(`<p class="book-subtitle"><em>${escapeHtml(meta.subtitle)}</em></p>`);
  if (meta.author) rows.push(`<p class="book-author">${escapeHtml(meta.author)}</p>`);
  if (meta.publisher) rows.push(`<p class="book-publisher">${escapeHtml(meta.publisher)}</p>`);
  return `<section class="front-matter title-page">\n${rows.join("\n")}\n</section>`;
}

export function copyrightPage(meta: ManuscriptMeta): string {
  const year = meta.year ?? String(new Date().getUTCFullYear());
  const holder = meta.copyright ?? meta.author ?? meta.title;
  const rows = [
    `<p class="copyright-line">Copyright &copy; ${escapeHtml(year)} ${escapeHtml(holder)}</p>`,
  ];
  if (meta.edition) rows.push(`<p>${escapeHtml(meta.edition)}</p>`);
  if (meta.publisher) rows.push(`<p>${escapeHtml(meta.publisher)}</p>`);
  if (meta.isbn) rows.push(`<p>ISBN ${escapeHtml(meta.isbn)}</p>`);
  rows.push(
    `<p class="rights">${escapeHtml(
      meta.rights ??
        "All rights reserved. No part of this book may be reproduced without written permission.",
    )}</p>`,
  );
  return `<section class="front-matter copyright-page">\n${rows.join("\n")}\n</section>`;
}

export function dedicationPage(meta: ManuscriptMeta): string {
  if (!meta.dedication) return "";
  return (
    `<section class="front-matter dedication">\n` +
    `<p class="dedication-text"><em>${escapeHtml(meta.dedication)}</em></p>\n</section>`
  );
}

export function epigraphPage(meta: ManuscriptMeta): string {
  if (!meta.epigraph) return "";
  const attribution = meta.epigraphAttribution
    ? `<p class="epigraph-attribution">&mdash; ${escapeHtml(meta.epigraphAttribution)}</p>`
    : "";
  return (
    `<section class="front-matter epigraph">\n` +
    `<blockquote class="epigraph-text"><p>${escapeHtml(meta.epigraph)}</p></blockquote>\n` +
    `${attribution}\n</section>`
  );
}

/**
 * Table of contents.
 *
 * Entries are hyperlinks to heading bookmarks, which survive to .docx and PDF —
 * verified against the live exporter. Two deliberate choices:
 *
 *   - The hierarchy is expressed with NESTED LISTS, not CSS classes. Class-based
 *     indentation looks right in the browser and arrives in Word as a flat list,
 *     because the exporter keeps structure and drops stylesheets.
 *   - There are no page numbers. Page numbers need pagination, which only exists
 *     once the renderer has laid the book out, and HTML has no way to express a
 *     Word TOC field. A fabricated number would be worse than none, so the entries
 *     are clickable instead. This is a stated limitation, not an oversight.
 */
export function tableOfContents(headings: HeadingRef[], depth: number): string {
  if (depth <= 0) return "";
  const items = headings.filter((h) => h.level <= depth);
  if (items.length === 0) return "";

  const rows: string[] = [];
  let current = items[0]!.level;
  rows.push("<ul class=\"toc-list\">");

  for (const h of items) {
    while (h.level > current) {
      rows.push("<ul>");
      current += 1;
    }
    while (h.level < current) {
      rows.push("</ul>");
      current -= 1;
    }
    // The nested list carries the structure; the em-space prefix carries the
    // *visible* indentation. Word and the PDF renderer both flatten nested-list
    // indentation from HTML, so structure alone would print as a flat column.
    const indent = h.level > 1 ? `<span class="toc-indent">${"&#8195;".repeat(h.level - 1)}</span>` : "";
    rows.push(
      `<li class="toc-entry toc-level-${h.level}">${indent}<a href="#${escapeAttr(
        h.anchor,
      )}">${escapeHtml(h.text)}</a></li>`,
    );
  }
  while (current > items[0]!.level) {
    rows.push("</ul>");
    current -= 1;
  }
  rows.push("</ul>");

  return `<section class="front-matter toc" id="mc-toc">\n<h1>Contents</h1>\n${rows.join("\n")}\n</section>`;
}

export function listOfFigures(figures: AssignedFigure[]): string {
  if (figures.length === 0) return "";
  const rows = figures.map(
    (f) =>
      `<li class="lof-entry"><a href="#${escapeAttr(f.anchor)}">${escapeHtml(f.label)}</a>${
        f.caption ? ` &mdash; ${f.caption}` : ""
      }</li>`,
  );
  return (
    `<section class="front-matter list-of-figures" id="mc-list-of-figures">\n` +
    `<h1>List of Figures</h1>\n<ul class="lof-list">\n${rows.join("\n")}\n</ul>\n</section>`
  );
}

/**
 * Bibliography, containing only the entries the manuscript actually cites.
 *
 * A reference list padded with uncited entries is a well-known way to look
 * better-read than you are; it also makes an editor's job harder. Cited-only is
 * the honest default, and the compile report says how many entries went unused.
 */
export function bibliographySection(
  bib: BibDatabase,
  citedKeys: string[],
  style: CitationStyle,
): string {
  if (citedKeys.length === 0) return "";
  const entries = citedKeys
    .map((k) => bib.entries.get(k))
    .filter((e): e is NonNullable<typeof e> => Boolean(e));
  if (entries.length === 0) return "";

  const numbers = new Map(citedKeys.map((k, i) => [k, i + 1]));
  const ordered =
    style === "numeric"
      ? entries
      : [...entries].sort((a, b) => bibSortKey(a).localeCompare(bibSortKey(b)));

  const rows = ordered.map(
    (e) =>
      `<li id="bib-${escapeAttr(e.key)}" class="bib-entry" data-cite-key="${escapeAttr(
        e.key,
      )}">${renderBibEntry(e, style, numbers.get(e.key) ?? 0)}</li>`,
  );
  return (
    `<section class="back-matter bibliography" id="mc-bibliography">\n<h1>Bibliography</h1>\n` +
    `<ul class="bib-list">\n${rows.join("\n")}\n</ul>\n</section>`
  );
}

export function notesSection(inner: string): string {
  if (!inner.trim()) return "";
  return `<section class="back-matter notes" id="mc-notes">\n<h1>Notes</h1>\n${inner}\n</section>`;
}

export function partTitlePage(part: string): string {
  return (
    `<section class="part-title" id="mc-part-${escapeAttr(
      part.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    )}">\n<h1 class="part-heading">${escapeHtml(part)}</h1>\n</section>`
  );
}
