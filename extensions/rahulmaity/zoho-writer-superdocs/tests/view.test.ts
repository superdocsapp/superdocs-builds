// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest";
import { createChangeCard } from "../src/view";

describe("change card rendering", () => {
  it("renders malicious external values as text, never markup", () => {
    const decide = vi.fn();
    const card = createChangeCard(
      {
        id: `"><img src=x onerror=alert(1)>`,
        operation: "unknown",
        chunkId: `<script>globalThis.pwned=true</script>`,
        oldHtml: `<img src=x onerror=alert(1)>`,
        newHtml: `<svg onload=alert(1)>after</svg>`,
        explanation: `<iframe srcdoc="<script>alert(1)</script>"></iframe>`,
      },
      decide,
    );

    expect(card.querySelector("img,script,svg,iframe")).toBeNull();
    expect(card.querySelector(".change-id")?.textContent).toContain("<script>");
    expect(card.querySelector(".before")?.textContent).toContain("<img");
    expect(card.querySelector(".after")?.textContent).toContain("<svg");
    expect(card.querySelector(".explanation")?.textContent).toContain("<iframe");
  });
});
