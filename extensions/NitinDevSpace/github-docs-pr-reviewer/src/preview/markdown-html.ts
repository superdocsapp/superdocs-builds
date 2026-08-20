import { marked } from "marked";
import type { ReviewableDoc } from "../review/scanner.js";

export function docsToHtml(docs: ReviewableDoc[], title = "Documentation preview"): string {
  const sections = docs
    .map((doc) => {
      const content = markdownToSafeHtml(doc.headContent ?? "");
      return `<section class="document" data-path="${escapeHtml(doc.path)}">
  <p class="path">${escapeHtml(doc.path)}</p>
  ${content || "<p><em>Empty document</em></p>"}
</section>`;
    })
    .join("\n");

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; color: #202124; background: #f4f6f8; line-height: 1.6; }
    main { max-width: 860px; margin: 0 auto; padding: 48px 28px; }
    header { border-bottom: 2px solid #202124; margin-bottom: 36px; padding-bottom: 20px; }
    h1, h2, h3 { line-height: 1.25; }
    .document { background: white; padding: 28px 34px; margin: 0 0 24px; box-shadow: 0 1px 4px #00000012; }
    .path { color: #5f6368; font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
    pre { overflow-x: auto; background: #f1f3f4; padding: 14px; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    img { max-width: 100%; }
  </style>
</head>
<body><main>
  <header><h1>${escapeHtml(title)}</h1><p>Generated from the documentation changes in this pull request.</p></header>
  ${sections || "<p>No reviewable documentation files were changed.</p>"}
</main></body>
</html>`;
}

/**
 * Renders untrusted Markdown to HTML with any embedded markup neutralised first.
 *
 * Documents and release notes are data this app reports on, never instructions or
 * markup it executes. Escaping before parsing means raw HTML in a source document
 * shows up as visible text in the preview instead of becoming live markup in the
 * artifact we hand back.
 */
export function markdownToSafeHtml(markdown: string): string {
  return marked.parse(escapeHtml(markdown), { async: false }) as string;
}

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character] ?? character);
}
