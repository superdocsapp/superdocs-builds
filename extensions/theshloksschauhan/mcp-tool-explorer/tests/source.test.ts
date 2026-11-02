import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "src");

async function sourceText(): Promise<string> {
  const files: string[] = [];
  async function walk(dir: string): Promise<void> {
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (/\.(ts|tsx|css)$/.test(entry.name)) files.push(full);
    }
  }
  await walk(root);
  const chunks = await Promise.all(files.map((file) => readFile(file, "utf8")));
  return chunks.join("\n");
}

describe("no hard-coded SuperDocs tool catalog", () => {
  it("does not embed known SuperDocs tool names or a static tool list", async () => {
    const source = await sourceText();
    const banned = [
      "list_sessions",
      "get_account_status",
      "upload_document_base64",
      "chat_async",
      "approve_change",
      "export_document",
      "const TOOLS",
      "toolCatalog",
      "hardcodedTools",
    ];
    for (const token of banned) expect(source.includes(token)).toBe(false);
  });
});
