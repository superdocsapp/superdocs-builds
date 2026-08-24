import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseDocumentInput } from "./documentInput.js";

const root = fileURLToPath(new URL("../../tests/fixtures/", import.meta.url));

describe("document input adapters", () => {
  it("accepts text and normalizes a BOM", () => {
    const result = parseDocumentInput("sample.txt", new TextEncoder().encode("\uFEFFHello manuscript"));
    expect(result.format).toBe("txt");
    expect(result.rawText).toBe("Hello manuscript");
  });

  it("extracts paragraph text and basic emphasis from DOCX without a third-party DOCX parser", () => {
    const bytes = readFileSync(join(root, "minimal.docx"));
    const result = parseDocumentInput("minimal.docx", bytes);
    expect(result.format).toBe("docx");
    expect(result.rawText).toContain("Veyra");
    expect(result.rawText).toContain("_Important_");
  });

  it("extracts text from a text-based PDF and rejects unsupported formats explicitly", () => {
    const pdf = readFileSync(join(root, "minimal.pdf"));
    const result = parseDocumentInput("minimal.pdf", pdf);
    expect(result.format).toBe("pdf");
    expect(result.rawText).toContain("Aetherfall");
    expect(() => parseDocumentInput("manuscript.rtf", new Uint8Array([1, 2, 3]))).toThrow(/Supported formats/);
  });
});
