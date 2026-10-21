/**
 * A self-contained HTML proof of the manuscript.
 *
 * This is the offline output: no key, no network, no cost. It exists so that the
 * compiler's real work — order, numbering, cross-references, citations — can be
 * checked and shipped by someone who has not signed up for anything. It also
 * gives the test suite something byte-comparable to assert against.
 *
 * The page styles are print-first (a measure of about 33em, real serif body text)
 * rather than a screen design pretending to be a book.
 */

import type { ManuscriptMeta } from "./types";
import { escapeHtml } from "./util";

const STYLES = `
:root {
  --ink: #16161a;
  --muted: #5d5d68;
  --rule: #d8d5cd;
  --page: #fbfaf7;
  --accent: #7a5c3e;
}
@media (prefers-color-scheme: dark) {
  :root { --ink: #e9e6df; --muted: #9d9a92; --rule: #3a3934; --page: #17171a; --accent: #c9a678; }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font: 1.05rem/1.65 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, "Times New Roman", serif;
}
main { max-width: 34em; margin: 0 auto; padding: 4rem 1.5rem 8rem; }
h1, h2, h3, h4, h5, h6 { font-weight: 600; line-height: 1.25; margin: 2.2em 0 0.6em; }
h1 { font-size: 1.9rem; }
h2 { font-size: 1.4rem; }
h3 { font-size: 1.15rem; }
p { margin: 0 0 1.1em; }
p + p { text-indent: 1.4em; margin-top: -0.6em; }
a { color: var(--accent); }
hr[data-page-break] {
  border: 0;
  border-top: 1px dashed var(--rule);
  margin: 3.5rem 0;
}
hr[data-page-break]::after {
  content: "page break";
  display: block;
  margin-top: -0.75em;
  text-align: center;
  font: 400 0.65rem/1 ui-sans-serif, system-ui, sans-serif;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
  background: var(--page);
  width: max-content;
  margin-inline: auto;
  padding: 0 0.6em;
}
.title-page { text-align: center; padding: 5rem 0 3rem; }
.book-title { font-size: 2.6rem; margin: 0 0 0.4em; }
.book-subtitle { color: var(--muted); font-size: 1.15rem; }
.book-author { margin-top: 2.5em; letter-spacing: 0.05em; }
.copyright-page, .dedication, .epigraph { color: var(--muted); font-size: 0.95rem; }
.dedication-text, .epigraph-text { text-align: center; }
.part-title { text-align: center; padding: 4rem 0; }
.part-heading { font-size: 2rem; letter-spacing: 0.06em; }
figure { margin: 2.2em 0; }
figure img { max-width: 100%; height: auto; display: block; margin: 0 auto; }
figcaption {
  margin-top: 0.7em;
  font: 400 0.85rem/1.5 ui-sans-serif, system-ui, sans-serif;
  color: var(--muted);
  text-align: center;
}
.figure-label { font-weight: 600; color: var(--ink); }
sup[data-footnote-ref] { color: var(--accent); font-weight: 600; padding-left: 0.1em; }
aside[data-part-type="footnote"] {
  border-top: 1px solid var(--rule);
  margin-top: 1.4em;
  padding-top: 0.6em;
  font-size: 0.85rem;
  color: var(--muted);
}
.toc-list, .lof-list, .bib-list { list-style: none; padding: 0; }
.toc-list ul { list-style: none; padding: 0; }
.toc-entry { padding: 0.18em 0; }
/* Indentation comes from the em-space prefix the compiler emits, so the screen
   and the printed page agree. Do not add padding here or it will double up. */
.toc-level-2 { font-size: 0.95rem; }
.toc-level-3 { font-size: 0.9rem; color: var(--muted); }
.bib-entry { margin: 0 0 0.8em; padding-left: 1.6em; text-indent: -1.6em; font-size: 0.95rem; }
blockquote {
  margin: 1.6em 0;
  padding-left: 1.2em;
  border-left: 2px solid var(--rule);
  color: var(--muted);
}
table { border-collapse: collapse; width: 100%; margin: 1.6em 0; font-size: 0.95rem; }
th, td { border: 1px solid var(--rule); padding: 0.45em 0.6em; text-align: left; }
code, pre { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.88em; }
pre { overflow-x: auto; padding: 1em; background: rgba(128,128,128,0.09); border-radius: 6px; }
.mc-unresolved, .citation-unresolved, .mc-missing-figure, .mc-missing-footnote {
  background: rgba(200, 60, 40, 0.14);
  color: #b03a2a;
  padding: 0 0.25em;
  border-radius: 3px;
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 0.85em;
}
@media print {
  body { background: #fff; }
  main { max-width: none; padding: 0; }
  hr[data-page-break] { border: 0; break-after: page; margin: 0; }
  hr[data-page-break]::after { content: none; }
}
`.trim();

export function renderStandaloneHtml(bodyHtml: string, meta: ManuscriptMeta): string {
  const title = escapeHtml(meta.title);
  const author = meta.author ? `<meta name="author" content="${escapeHtml(meta.author)}">` : "";
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
${author}
<style>
${STYLES}
</style>
</head>
<body>
<main>
${bodyHtml}
</main>
</body>
</html>
`;
}
