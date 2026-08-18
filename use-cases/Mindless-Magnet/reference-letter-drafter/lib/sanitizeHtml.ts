import DOMPurify from "dompurify";

const ALLOWED_TAGS = ["p", "h1", "h2", "h3", "br", "strong", "em", "ul", "ol", "li", "u"];
const ALLOWED_ATTR = ["data-chunk-id"];

// DOMPurify has no DOM to work with during SSR (Next.js renders client
// components on the server too). Importing it is safe there — it just
// doesn't get a usable `window` — but calling `.sanitize` must be skipped.
export function sanitizeHtml(html: string): string {
  if (typeof window === "undefined") {
    return html;
  }
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR });
}
