// @vitest-environment jsdom

import { describe, expect, it } from "vitest";
import { createChangeCard, readableText } from "../src/view";

describe("change card rendering", () => {
  it("renders malicious external values as text, never markup", () => {
    const card = createChangeCard({
      id: `"><img src=x onerror=alert(1)>`,
      operation: "unknown",
      chunkId: `<script>globalThis.pwned=true</script>`,
      oldHtml: `<img src=x onerror=alert(1)>`,
      newHtml: `<svg onload=alert(1)>after</svg>`,
      explanation: `<iframe srcdoc="<script>alert(1)</script>"></iframe>`,
    });

    // The card must never contain a live element built from proposal content.
    expect(card.querySelector("img,script,svg,iframe")).toBeNull();
    expect(card.querySelector(".change-id")?.textContent).toContain("<script>");
    expect(card.querySelector(".explanation")?.textContent).toContain("<iframe");
    // The markup view still shows the raw source verbatim, as text.
    expect(card.querySelector(".markup .before")?.textContent).toContain("<img");
    expect(card.querySelector(".markup .after")?.textContent).toContain("<svg");
    expect(globalThis).not.toHaveProperty("pwned");
  });

  it("shows the wording a reviewer decides on, not its tags", () => {
    const card = createChangeCard({
      id: "c1",
      operation: "edit",
      oldHtml: "<p>I am an <b>AI</b> engineer</p>",
      newHtml: "<p>I am an <b>artificial intelligence</b> engineer</p>",
      explanation: "More formal.",
    });

    expect(card.querySelector(".prose.before")?.textContent).toBe(
      "I am an AI engineer",
    );
    expect(card.querySelector(".prose.after")?.textContent).toBe(
      "I am an artificial intelligence engineer",
    );
  });

  it("extracts text without executing or attaching the parsed markup", () => {
    expect(readableText("<p>Hello   there</p>\n<p>again</p>")).toBe(
      "Hello there again",
    );
    // Markup carrying no words has nothing to review.
    expect(readableText("<img src=x onerror=alert(1)>")).toBe("");
    expect(readableText("")).toBe("");
  });
});
