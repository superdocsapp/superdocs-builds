import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function readUi(fileName: string): string {
  return readFileSync(resolve(process.cwd(), fileName), "utf8");
}

describe("sidebar UI contract", () => {
  const sidebar = readUi("sidebar/index.html");

  it("exposes the implemented generation controls", () => {
    for (const id of ["previewButton", "generateButton", "resumeButton", "cancelButton", "progressBar", "status"]) {
      expect(sidebar).toContain(`id="${id}"`);
    }
    expect(sidebar).toContain('id="emailToggle"');
  });

  it("wires preview, generation, resume, cancellation, and status actions", () => {
    for (const action of ["preview()", "generate()", "resume()", "cancelJob()", "getInitialState", "advanceGeneration"]) {
      expect(sidebar).toContain(action);
    }
    expect(sidebar).toContain("google.script.run");
    expect(sidebar).toContain("withSuccessHandler");
    expect(sidebar).toContain("withFailureHandler");
  });

  it("includes live progress and row-level status reporting", () => {
    expect(sidebar).toContain("completedRows");
    expect(sidebar).toContain("totalRows");
    expect(sidebar).toContain("failed");
    expect(sidebar).toContain("Emails sent");
  });

  it("uses the solid document-workspace visual system", () => {
    expect(sidebar).toContain("--coral:#ee735f");
    expect(sidebar).toContain("background:var(--canvas)");
    expect(sidebar).toContain("border-radius:0");
    expect(sidebar).toContain(".button.primary { background:var(--coral)");
  });
});

describe("settings UI contract", () => {
  const settings = readUi("settings/index.html");

  it("provides a secure API-key input and save action", () => {
    expect(settings).toContain('type="password"');
    expect(settings).toContain("saveSuperDocsApiKey");
    expect(settings).toContain("getSettingsState");
    expect(settings).toContain("withFailureHandler");
  });

  it("uses the same solid boxed visual system as the sidebar", () => {
    expect(settings).toContain("--coral:#ee735f");
    expect(settings).toContain("background:var(--canvas)");
    expect(settings).toContain("border-radius:0");
  });
});
