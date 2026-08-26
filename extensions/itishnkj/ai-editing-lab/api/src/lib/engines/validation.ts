import sanitizeHtml from "sanitize-html";

const MAX_DOCUMENT_CHARS = 200_000;
const ALLOWED_TAGS = [
  "a",
  "b",
  "blockquote",
  "br",
  "code",
  "del",
  "div",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "i",
  "li",
  "ol",
  "p",
  "pre",
  "s",
  "span",
  "strong",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "u",
  "ul",
];

export function sanitizeDocumentHtml(html: string): string {
  return sanitizeHtml(html, {
    allowedTags: ALLOWED_TAGS,
    allowedAttributes: {
      "*": ["data-chunk-id"],
      a: ["href", "target", "rel", "title"],
      td: ["colspan", "rowspan"],
      th: ["colspan", "rowspan"],
      ol: ["start", "reversed", "type"],
      li: ["value"],
    },
    allowedSchemes: ["http", "https", "mailto", "tel"],
    allowedSchemesAppliedToAttributes: ["href"],
    allowProtocolRelative: false,
    disallowedTagsMode: "discard",
  });
}

export function validateDocumentHtml(html: string): string {
  if (!html.trim()) {
    throw new Error("The document is empty.");
  }
  if (html.length > MAX_DOCUMENT_CHARS) {
    throw new Error(
      `The document exceeds the ${MAX_DOCUMENT_CHARS.toLocaleString()} character safety limit.`,
    );
  }
  return sanitizeDocumentHtml(html);
}