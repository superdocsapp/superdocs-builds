import { createWriteStream } from "node:fs";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { ReadableStream as NodeReadableStream } from "node:stream/web";
import type { SuperDocsClient } from "./client.js";

export type ExportFormat = "docx" | "pdf" | "html" | "markdown" | "txt";

const EXTENSION: Record<ExportFormat, string> = {
  docx: "docx",
  pdf: "pdf",
  html: "html",
  markdown: "md",
  txt: "txt",
};

async function streamToFile(url: string, destPath: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok || !res.body) {
    throw new Error(`failed to download export from pre-signed URL: ${res.status} ${res.statusText}`);
  }
  // The bytes are streamed straight from the pre-signed URL to disk — they
  // never pass through the agent's (LLM) context.
  // DOM's ReadableStream (fetch's lib.dom type) and Node's stream/web
  // ReadableStream are structurally identical at runtime but typed
  // separately across lib defs — cast through the Node type Readable.fromWeb expects.
  await pipeline(
    Readable.fromWeb(res.body as unknown as NodeReadableStream<Uint8Array>),
    createWriteStream(destPath),
  );
}

export async function exportReport(
  client: SuperDocsClient,
  sessionId: string,
  formats: ExportFormat[],
  outDir: string,
): Promise<string[]> {
  await mkdir(outDir, { recursive: true });
  const outputPaths: string[] = [];

  for (const format of formats) {
    // filename is intentionally left unset here: exportReport doesn't
    // receive the report's title, and the server's own auto-detection from
    // the document's first heading is more sensible than a generic name
    // derived from the session id.
    const { download_url, filename } = await client.requestDownloadUrl({
      session_id: sessionId,
      format,
      options: {
        paper_size: "A4",
        orientation: "portrait",
      },
    });

    // filename comes back WITH an extension already (despite the request
    // param being described as "without extension") — strip whatever's
    // there before appending the one that matches this format.
    const baseName = path.basename(filename, path.extname(filename));
    const destPath = path.resolve(outDir, `${baseName}.${EXTENSION[format]}`);
    await streamToFile(download_url, destPath);
    outputPaths.push(destPath);
    console.log(`[OK] exported ${format}: ${destPath}`);
  }

  return outputPaths;
}
