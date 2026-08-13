import { describe, expect, it } from "vitest";
import { exampleInput, makeKitHtml } from "./kit";
import { displayWidth, validateTranslations } from "./validation";

describe("localization validation", () => {
  it("preserves every token including markup", () => {
    const results = validateTranslations(
      [{ id: "A", source: "Use {name} at [BTN_OK] <b>now</b>", characterLimit: 80, speaker: "", scene: "" }],
      { A: "{name}を今使う [BTN_OK]" },
      "Japanese",
    );
    expect(results.some(result => result.kind === "missing_token")).toBe(true);
  });

  it("uses target-script display width rather than character count", () => {
    expect(displayWidth("警告", "Japanese")).toBe(4);
    expect(validateTranslations([{ id: "A", source: "Warning", characterLimit: 3, speaker: "", scene: "" }], { A: "警告" }, "Japanese").some(result => result.kind === "limit")).toBe(true);
  });

  it("includes stable chunk IDs in the generated SuperDocs HTML", () => {
    const html = makeKitHtml(exampleInput);
    expect(html).toContain('data-chunk-id="00000000-0000-4000-8000-000000000001"');
    expect(html).toContain('data-chunk-id="00000000-0000-4000-8000-000000000008"');
  });
});
