import type { PaperDocument } from "./types.js";

export function renderMarkdown(paper: PaperDocument): string {
  const lines: string[] = [`# ${paper.title}`, ""];

  for (const block of paper.blocks) {
    if (block.type === "heading") {
      lines.push(`## ${block.content}`, "");
      continue;
    }

    if (block.type === "paragraph") {
      lines.push(block.content, "");
      continue;
    }

    if (block.type === "equation") {
      if (block.metadata?.display === false) {
        lines.push(`$${block.content}$`, "");
      } else {
        lines.push("$$", block.content, "$$", "");
      }
      continue;
    }

    if (block.type === "figure") {
      const figureNumber = block.metadata?.figureNumber;
      const caption = block.content;
      const mimeType = block.metadata?.mimeType;
      const imageBase64 = block.metadata?.imageBase64;
      const image = typeof mimeType === "string" && typeof imageBase64 === "string"
        ? `![${caption}](data:${mimeType};base64,${imageBase64})`
        : `[Figure ${String(figureNumber)} image unavailable]`;
      lines.push(
        image,
        "",
        caption,
        "",
      );
      continue;
    }

    if (block.type === "conflict") {
      lines.push(`> ⚠️ ${block.content}`, "");
      continue;
    }

    lines.push(block.content, "");
  }

  return lines.join("\n");
}
