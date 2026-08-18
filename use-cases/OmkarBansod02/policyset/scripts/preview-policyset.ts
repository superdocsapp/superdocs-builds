import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { NORTHSTAR_GOODS_PROFILE } from "../src/domain";
import { generatePolicyDocuments } from "../src/documents";
import { SuperDocsClient, createSessionId } from "../src/superdocs";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const previewDir = path.join(rootDir, "tmp", "policyset-preview");

async function main(): Promise<void> {
  const upload = process.argv.includes("--upload");
  const generated = await generatePolicyDocuments(NORTHSTAR_GOODS_PROFILE);

  await mkdir(previewDir, { recursive: true });
  for (const document of generated.documents) {
    const filePath = path.join(previewDir, document.filename);
    await writeFile(filePath, document.bytes);
    console.log(filePath);
  }

  if (!upload) {
    return;
  }

  const apiKey = process.env.SUPERDOCS_API_KEY?.trim();
  if (!apiKey) {
    console.error("SUPERDOCS_API_KEY is required for --upload");
    process.exitCode = 1;
    return;
  }

  const sessionId = createSessionId();
  const client = new SuperDocsClient({ apiKey });

  for (const [index, document] of generated.documents.entries()) {
    await client.uploadDocx({
      sessionId,
      filename: document.filename,
      bytes: document.bytes,
      openMode: index === 0 ? "replace" : "background",
    });
  }

  const roster = await client.listSessionDocuments(sessionId, {
    includeHtml: false,
  });

  console.log(`session id: ${sessionId}`);
  for (const document of roster) {
    console.log(
      `${document.title ?? "(untitled)"}: ${document.identity.documentId}`,
    );
  }
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : "preview failed";
  console.error(message);
  process.exitCode = 1;
});
