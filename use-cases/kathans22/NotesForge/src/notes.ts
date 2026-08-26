import { readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { CONFIG } from "./config.js";
import type { SuperDocsClient } from "./client.js";
import type { ProcessDocumentResponse } from "./types.js";

const ALLOWED_EXTENSIONS = new Set([".md", ".txt", ".rtf", ".html"]);
const MAX_INGEST_BYTES = 5 * 1024 * 1024;

export interface NoteFile {
  path: string;
  name: string;
  ext: string;
  bytes: number;
  content: string;
  isLarge: boolean;
}

async function walk(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    if (entry.name.startsWith(".")) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walk(full)));
    } else if (entry.isFile()) {
      files.push(full);
    }
  }
  return files;
}

export async function readNotes(dir: string): Promise<NoteFile[]> {
  let candidates: string[];
  try {
    candidates = await walk(dir);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error(
        `notes folder not found: ${dir} — create it and add some .md/.txt/.rtf/.html files first`,
      );
    }
    throw err;
  }

  const notes: NoteFile[] = [];
  for (const filePath of candidates) {
    const name = path.basename(filePath);
    const ext = path.extname(filePath).toLowerCase();
    if (!ALLOWED_EXTENSIONS.has(ext)) continue;

    const { size } = await stat(filePath);
    if (size > MAX_INGEST_BYTES) {
      console.warn(`[WARN] skipping ${name}: ${size} bytes exceeds the 5MB ingestion limit`);
      continue;
    }

    const content = await readFile(filePath, "utf8");
    notes.push({
      path: filePath,
      name,
      ext,
      bytes: size,
      content,
      isLarge: size > CONFIG.INLINE_UPLOAD_MAX_BYTES,
    });
  }

  if (notes.length === 0) {
    throw new Error(
      `no .md/.txt/.rtf/.html notes found in ${dir} — add some files, or check the folder path`,
    );
  }

  return notes.sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * One consolidated digest for the whole notes folder — one digest, one AI
 * request, one operation. Never loop a chat call per file.
 */
export function summariseNotes(notes: NoteFile[]): string {
  const totalChars = notes.reduce((sum, n) => sum + n.content.length, 0);
  const header = `# ${notes.length} note file(s), ${totalChars} total characters`;
  const sections = notes.map((n) => `### ${n.name}\n\n${n.content}`);
  return [header, ...sections].join("\n\n");
}

export interface UploadStrategy {
  inline: NoteFile[];
  presigned: NoteFile[];
}

/**
 * Only the split + logging happens here — the actual pre-signed upload flow
 * for `presigned` files is Prompt 11's job.
 */
export function planUploadStrategy(notes: NoteFile[]): UploadStrategy {
  const inline = notes.filter((n) => !n.isLarge);
  const presigned = notes.filter((n) => n.isLarge);

  if (presigned.length > 0) {
    console.log(
      `[INFO] ${presigned.length} file(s) over ${CONFIG.INLINE_UPLOAD_MAX_BYTES} bytes will go through the pre-signed upload flow so their bytes never pass through this agent's context window: ${presigned
        .map((n) => n.name)
        .join(", ")}`,
    );
  } else {
    console.log(`[INFO] all ${inline.length} file(s) are small enough to send inline`);
  }

  return { inline, presigned };
}

const CONTENT_TYPE_BY_EXT: Record<string, string> = {
  ".md": "text/markdown",
  ".txt": "text/plain",
  ".rtf": "application/rtf",
  ".html": "text/html",
};

export interface UploadLargeNoteResult {
  sessionId: string;
  result: ProcessDocumentResponse;
}

/**
 * The pre-signed path for a note over CONFIG.INLINE_UPLOAD_MAX_BYTES:
 * request an upload URL, PUT the bytes directly to it, then have the
 * server parse what it already received. Uploading and loading the file is
 * NOT billed — billing only starts once the AI actually reads/edits it.
 */
export async function uploadLargeNote(
  client: SuperDocsClient,
  note: NoteFile,
): Promise<UploadLargeNoteResult> {
  const contentType = CONTENT_TYPE_BY_EXT[note.ext] ?? "text/plain";

  const { upload_id, upload_url } = await client.requestUploadUrl({
    filename: note.name,
    content_type: contentType,
    size_bytes: note.bytes,
    purpose: "attachment",
  });

  const putRes = await fetch(upload_url, {
    method: "PUT",
    headers: { "Content-Type": contentType },
    body: note.content,
  });
  if (!putRes.ok) {
    throw new Error(
      `uploadLargeNote: PUT to pre-signed URL failed for ${note.name}: ${putRes.status} ${putRes.statusText}`,
    );
  }

  const sessionId = `notesforge-attachment-${Date.now()}`;
  const result = await client.processUpload(upload_id, {
    session_id: sessionId,
    filename: note.name,
    parse_mode: "attachment",
    return_html: false,
  });

  return { sessionId, result };
}
