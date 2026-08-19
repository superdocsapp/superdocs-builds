/**
 * HTML -> plain text, with no DOM and no dependency.
 *
 * The audit runs on the server (Node) and inside tests (also Node), so it
 * cannot reach for `document`. This does not need to be a general-purpose HTML
 * parser: the input is SuperDocs' own chunked output, which is a small, sane
 * subset — paragraphs, headings, lists, inline emphasis.
 *
 * Block-level tags become newlines so that sentence-boundary logic in the
 * audit does not run two paragraphs together.
 */

const BLOCK_TAGS = /<\/?(p|div|h[1-6]|li|ul|ol|br|tr|table|section|blockquote)[^>]*>/gi;

const ENTITIES: Record<string, string> = {
  "&nbsp;": " ",
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&apos;": "'",
  "&mdash;": "-",
  "&ndash;": "-",
  "&hellip;": "...",
  "&rsquo;": "'",
  "&lsquo;": "'",
  "&rdquo;": '"',
  "&ldquo;": '"',
};

export function textFromHtml(html: string): string {
  if (!html) return "";

  return html
    .replace(/<(script|style)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(BLOCK_TAGS, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/&[a-z]+;|&#\d+;/gi, (entity) => ENTITIES[entity.toLowerCase()] ?? " ")
    .replace(/[ \t\u00a0]+/g, " ")
    // `</p><p>` emits two newlines; a closing tag next to an opening one is a
    // single boundary, not a blank line. Collapse any run to one separator so
    // downstream sentence logic sees a predictable shape.
    .replace(/\n[\s\n]*\n/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .join("\n")
    .trim();
}
