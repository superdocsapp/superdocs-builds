import DOMPurify from "dompurify";

/**
 * Sanitizes SuperDocs-returned HTML before it is ever rendered with
 * `dangerouslySetInnerHTML`, in the one place this app does that: the full
 * letter preview, so formatting-only changes (spacing, emphasis) are
 * actually visible — the per-change diff cards stay plain-text word diffs on
 * purpose, since a word-level diff is a better review tool for content edits
 * than raw markup is.
 *
 * `style` is allowed so that content like `margin-bottom` survives; DOMPurify
 * still strips dangerous CSS (`expression()`, `url(javascript:...)`, etc.)
 * out of whatever the style attribute contains, so allowing the attribute is
 * not the same as trusting its contents.
 *
 * `.sanitize()` needs a DOM, so it only runs in the browser. Static top-level
 * `import DOMPurify from "dompurify"` is safe to evaluate on the server (it
 * does not touch `window` at import time) — only the call is guarded.
 */

const ALLOWED_TAGS = ["p", "h1", "h2", "h3", "br", "strong", "em", "b", "i", "u", "ul", "ol", "li", "span"];
const ALLOWED_ATTR = ["data-chunk-id", "style"];

export function sanitizeHtml(html: string): string {
  if (typeof window === "undefined") return html;
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR });
}
