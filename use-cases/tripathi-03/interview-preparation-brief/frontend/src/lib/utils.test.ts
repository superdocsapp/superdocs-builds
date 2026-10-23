import { describe, expect, it } from "vitest";

import { cn, stripHtml } from "@/lib/utils";

describe("utils", () => {
  it("merges class names", () => {
    expect(cn("px-2", false && "hidden", "py-1")).toContain("px-2");
    expect(cn("px-2", "px-4")).toContain("px-4");
  });

  it("strips html to text", () => {
    expect(stripHtml("<p>Hello <strong>world</strong></p>")).toBe("Hello world");
  });
});
