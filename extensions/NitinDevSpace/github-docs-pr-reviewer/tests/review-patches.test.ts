import { describe, expect, it } from "vitest";
import {
  applyLineAutofix,
  changedLineNumbers,
  type LineAutofix
} from "../src/review/patches.js";

function autofix(overrides: Partial<LineAutofix> = {}): LineAutofix {
  return {
    kind: "replace-line",
    line: 2,
    before: "Utilize the API.",
    after: "Use the API.",
    ...overrides
  };
}

describe("line autofix applier", () => {
  it("changes only the targeted line and proves it", () => {
    const content = "# Title\nUtilize the API.\nUnrelated line.\n";

    const result = applyLineAutofix(content, autofix());

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.content).toBe("# Title\nUse the API.\nUnrelated line.\n");
    expect(result.changedLines).toEqual([2]);
  });

  it("keeps every untouched byte identical", () => {
    const content = "# Title\nUtilize the API.\nUnrelated line.\n";

    const result = applyLineAutofix(content, autofix());

    expect(result.ok).toBe(true);
    if (!result.ok) return;

    const before = content.split("\n");
    const after = result.content.split("\n");
    expect(after.length).toBe(before.length);
    for (let index = 0; index < before.length; index += 1) {
      if (index === 1) continue;
      expect(after[index]).toBe(before[index]);
    }
  });

  it("preserves CRLF line endings", () => {
    const content = "# Title\r\nUtilize the API.\r\nUnrelated line.\r\n";

    const result = applyLineAutofix(content, autofix());

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.content).toBe(
      "# Title\r\nUse the API.\r\nUnrelated line.\r\n"
    );
  });

  it("preserves a missing trailing newline", () => {
    const content = "# Title\nUtilize the API.";

    const result = applyLineAutofix(content, autofix());

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.content).toBe("# Title\nUse the API.");
  });

  it("refuses when the anchored line has drifted", () => {
    const content = "# Title\nSomeone already rewrote this line.\n";

    const result = applyLineAutofix(content, autofix());

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.refusal).toBe("content-drift");
  });

  it("refuses when the line no longer exists", () => {
    const result = applyLineAutofix("# Title\n", autofix({ line: 9 }));

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.refusal).toBe("line-out-of-range");
  });

  it("refuses an empty file", () => {
    const result = applyLineAutofix("", autofix());

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.refusal).toBe("empty-file");
  });

  it("refuses a fix that would change nothing", () => {
    const content = "# Title\nUse the API.\n";

    const result = applyLineAutofix(
      content,
      autofix({ before: "Use the API.", after: "Use the API." })
    );

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.refusal).toBe("no-op");
  });
});

describe("changed line proof", () => {
  it("reports no changed lines for identical content", () => {
    expect(changedLineNumbers("a\nb\n", "a\nb\n")).toEqual([]);
  });

  it("reports a changed line ending as a change", () => {
    expect(changedLineNumbers("a\nb\n", "a\r\nb\n")).toEqual([1]);
  });

  it("reports appended lines", () => {
    expect(changedLineNumbers("a\n", "a\nb\n")).toEqual([2]);
  });
});
