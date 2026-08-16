import type { PaperDocument } from "./types.js";

export function renderHtml(paper: PaperDocument): string {
  const blocks = paper.blocks.map((block) => {
    if (block.type === "heading") return `<h2>${escapeHtml(block.content)}</h2>`;
    if (block.type === "paragraph") return `<p>${escapeHtml(block.content)}</p>`;
    if (block.type === "equation") {
      const delimiter = block.metadata?.display === false ? "$" : "$$";
      return `<div data-equation="true"><span>${delimiter}${escapeHtml(block.content)}${delimiter}</span></div>`;
    }
    if (block.type === "figure") {
      const mimeType = block.metadata?.mimeType;
      const imageBase64 = block.metadata?.imageBase64;
      const image = typeof mimeType === "string" && typeof imageBase64 === "string"
        ? `<img src="data:${escapeAttribute(mimeType)};base64,${escapeAttribute(imageBase64)}" alt="${escapeAttribute(block.content)}">`
        : "";
      return `<figure>${image}<figcaption>${escapeHtml(block.content)}</figcaption></figure>`;
    }
    if (block.type === "conflict") return `<aside data-conflict="true"><strong>Warning:</strong> ${escapeHtml(block.content)}</aside>`;
    return `<p>${escapeHtml(block.content)}</p>`;
  });

  return `<h1>${escapeHtml(paper.title)}</h1>${blocks.join("")}`;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttribute(value: string): string {
  return escapeHtml(value);
}
