import { describe, expect, it } from "vitest";
import { exampleInput, filterStrings, makeKitHtml } from "./kit";
import { parsePendingChanges } from "./superdocs";
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

  it("requires repeated tokens and protected proper nouns to survive", () => {
    const results = validateTranslations(
      [{ id: "A", source: "Rook protects Rook with {shield} and {shield}", characterLimit: 80, speaker: "", scene: "" }],
      { A: "Rook protects with {shield}" },
      "English",
      ["Rook"],
    );
    expect(results.some(result => result.kind === "missing_token")).toBe(true);
    expect(results.some(result => result.kind === "missing_protected_term")).toBe(true);
  });

  it("parses both array and double-encoded SuperDocs change payloads", () => {
    const change = { change_id: "change-1", operation: "edit", old_html: "<p>old</p>", new_html: "<p>new</p>", ai_explanation: "Clearer context" };
    expect(parsePendingChanges({ pending_changes: [change] })).toEqual([change]);
    expect(parsePendingChanges({ pending_changes: JSON.stringify(JSON.stringify([change])) })).toEqual([change]);
  });

  it("includes stable chunk IDs in the generated SuperDocs HTML", () => {
    const html = makeKitHtml(exampleInput);
    expect(html).toContain('data-chunk-id="00000000-0000-4000-8000-000000000001"');
    expect(html).toContain('data-chunk-id="00000000-0000-4000-8000-000000000008"');
  });

  it("filters a large string table by workflow-relevant context", () => {
    expect(filterStrings(exampleInput.strings, "breach").map(item => item.id)).toEqual(["DIA.ROOK.ENTRY"]);
    expect(filterStrings(exampleInput.strings, "HUD").map(item => item.id)).toEqual(["HUD.REACTOR.OVERLOAD"]);
  });
});
