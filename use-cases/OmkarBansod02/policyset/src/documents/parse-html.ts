type HeadingBlock = {
  kind: "heading";
  level: 1 | 2;
  text: string;
};

type ParagraphBlock = {
  kind: "paragraph";
  text: string;
};

type FactBlock = {
  kind: "fact";
  label: string;
  value: string;
};

export type DocumentBlock = HeadingBlock | ParagraphBlock | FactBlock;

export function parseRendererHtml(html: string): DocumentBlock[] {
  const withoutFooter = html.replace(/<footer\b[\s\S]*?<\/footer>/i, "");
  const blocks: DocumentBlock[] = [];
  const tagPattern = /<(h1|h2|p|dt|dd)(?:\s[^>]*)?>([\s\S]*?)<\/\1>/gi;
  let pendingLabel: string | null = null;

  for (const match of withoutFooter.matchAll(tagPattern)) {
    const tag = match[1].toLowerCase();
    const text = innerText(match[2]);
    if (!text) {
      continue;
    }

    if (tag === "dt") {
      pendingLabel = text;
      continue;
    }

    if (tag === "dd") {
      blocks.push({
        kind: "fact",
        label: pendingLabel ?? "Fact",
        value: text,
      });
      pendingLabel = null;
      continue;
    }

    if (tag === "h1") {
      blocks.push({ kind: "heading", level: 1, text });
      continue;
    }

    if (tag === "h2") {
      blocks.push({ kind: "heading", level: 2, text });
      continue;
    }

    blocks.push({ kind: "paragraph", text });
  }

  return blocks;
}

function innerText(html: string): string {
  return decodeEntities(html.replace(/<[^>]+>/g, ""))
    .replace(/\s+/g, " ")
    .trim();
}

function decodeEntities(value: string): string {
  return value
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'");
}
