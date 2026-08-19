import { describe, expect, it } from "vitest";
import { sanitizeHtml } from "@/lib/sanitizeHtml";

/**
 * The test suite runs with `environment: "node"` (see vitest.config.ts) — no
 * DOM, so no real DOMPurify sanitization to exercise here. What IS worth a
 * test: the server-side guard. An earlier version of this file crashed
 * exactly here — `.sanitize()` was reachable outside a browser and threw.
 * `dangerouslySetInnerHTML` only ever runs client-side in this app (see
 * components/LetterPreview.tsx), so passing HTML through unchanged when
 * `window` is undefined is correct, not a bypass.
 */
describe("sanitizeHtml", () => {
  it("passes HTML through unchanged outside a browser, rather than throwing", () => {
    const html = "<p>Hello.</p>";
    expect(sanitizeHtml(html)).toBe(html);
  });

  it("returns an empty string as-is", () => {
    expect(sanitizeHtml("")).toBe("");
  });
});
