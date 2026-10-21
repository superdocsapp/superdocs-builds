/**
 * Getting figures into the exported book.
 *
 * A local vault path in `<img src>` means nothing to a server-side renderer, and
 * — verified against the live exporter — a `data:` URI is dropped from the .docx
 * and the PDF **with no export warning at all**. A figure that is not uploaded
 * simply is not in the book, silently. So every figure is uploaded once, and the
 * resulting URL is cached by content hash in the manifest.
 *
 * Content-addressing is what makes recompiling cheap: editing chapter nine's prose
 * re-uploads nothing, and swapping one plate re-uploads exactly that plate.
 */

import type { Diagnostic, VaultReader } from "../core/types";
import type { AssignedFigure } from "../core/numbering";
import type { SuperDocsClient } from "./client";
import { extOf, hashFull } from "../core/util";

const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

const MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  svg: "image/svg+xml",
  bmp: "image/bmp",
  avif: "image/avif",
};

export interface UploadFiguresArgs {
  html: string;
  figures: AssignedFigure[];
  vault: VaultReader;
  client: SuperDocsClient;
  /** sha256 -> URL, carried across compiles in the manifest. Mutated in place. */
  cache: Record<string, string>;
  onProgress?: (done: number, total: number) => void;
  /** Aborts between uploads, so a long export can be cancelled. */
  signal?: { aborted: boolean };
  /**
   * How many uploads may be in flight at once.
   *
   * Serial uploads were the worst path in the codebase for a long book: an
   * illustrated 300-page manuscript has ~120 plates, and one round trip each meant
   * the export sat still for the better part of a minute. Six is deliberately
   * modest — the ceiling here is the API's patience, not the local CPU, and a
   * figure upload that gets rate-limited costs more than it saves.
   */
  concurrency?: number;
}

export interface UploadFiguresResult {
  html: string;
  diagnostics: Diagnostic[];
  uploaded: number;
  reused: number;
}

export async function uploadFigures(args: UploadFiguresArgs): Promise<UploadFiguresResult> {
  const diagnostics: Diagnostic[] = [];
  const replacements = new Map<string, string>();
  let uploaded = 0;
  let reused = 0;

  const local = args.figures.filter((f) => f.sourcePath && !/^https?:/i.test(f.sourcePath));

  /**
   * Uploads in flight, keyed by content hash.
   *
   * Serially this was free: the second copy of an image always found the first in
   * the cache. Running uploads concurrently reintroduces the duplicate — two
   * identical plates start before either finishes and the same bytes go up twice.
   * Sharing the promise keeps content-addressing honest under concurrency.
   */
  const inFlight = new Map<string, Promise<string>>();

  let done = 0;
  const total = local.length;
  const tick = () => args.onProgress?.(done, total);
  tick();

  const uploadOne = async (figure: (typeof local)[number]): Promise<void> => {
    if (args.signal?.aborted) return;
    const path = figure.sourcePath!;

    let bytes: Uint8Array;
    try {
      bytes = await args.vault.readBinary(path);
    } catch {
      diagnostics.push({
        severity: "error",
        code: "figure.unreadable",
        message: `"${path}" could not be read, so ${figure.label} will be missing from the exported book.`,
        file: path,
      });
      return;
    }

    if (bytes.byteLength > MAX_IMAGE_BYTES) {
      diagnostics.push({
        severity: "error",
        code: "figure.too_large",
        message: `"${path}" is ${(bytes.byteLength / 1024 / 1024).toFixed(
          1,
        )} MB; the limit is 10 MB. ${figure.label} will be missing from the exported book. Downsample it — print does not need more than about 300 dpi at the printed size.`,
        file: path,
      });
      return;
    }

    const digest = hashFull(bytes);

    const cached = args.cache[digest];
    if (cached) {
      replacements.set(path, cached);
      reused += 1;
      return;
    }

    const pending = inFlight.get(digest);
    if (pending) {
      try {
        replacements.set(path, await pending);
        reused += 1;
      } catch {
        // The upload that owns this digest reports its own failure.
      }
      return;
    }

    const ext = extOf(path);
    if (!MIME[ext]) {
      diagnostics.push({
        severity: "warning",
        code: "figure.unsupported_format",
        message: `"${path}" has an image extension the exporter does not accept (${ext}). ${figure.label} will be missing from the exported book.`,
        file: path,
      });
      return;
    }

    const job = args.client
      .uploadImage({ base64: toBase64(bytes), filename: path.split("/").pop() ?? `figure.${ext}` })
      .then(({ url }) => {
        args.cache[digest] = url;
        return url;
      });
    inFlight.set(digest, job);

    try {
      replacements.set(path, await job);
      uploaded += 1;
    } catch (err) {
      diagnostics.push({
        severity: "error",
        code: "figure.upload_failed",
        message: `Uploading "${path}" failed (${
          err instanceof Error ? err.message : String(err)
        }). ${figure.label} will be missing from the exported book.`,
        file: path,
      });
    }
  };

  // A fixed pool of workers pulling from one queue: steady pressure on the API
  // without building a 120-deep promise pile up front.
  const limit = Math.max(1, args.concurrency ?? 6);
  let next = 0;
  const worker = async (): Promise<void> => {
    for (;;) {
      if (args.signal?.aborted) return;
      const index = next++;
      if (index >= local.length) return;
      await uploadOne(local[index]!);
      done += 1;
      tick();
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, local.length) }, worker));

  if (args.signal?.aborted) {
    diagnostics.push({
      severity: "warning",
      code: "figure.upload_cancelled",
      message: `Figure upload was cancelled after ${done} of ${total}. Nothing was exported.`,
    });
  }

  return {
    html: rewriteImageSources(args.html, replacements),
    diagnostics,
    uploaded,
    reused,
  };
}

/**
 * Swap local `src` values for hosted URLs.
 *
 * Only `<img>` elements the compiler emitted are touched, matched on the exact
 * vault path it wrote there — no general HTML rewriting, so author content that
 * merely mentions a path is untouched.
 */
export function rewriteImageSources(html: string, replacements: Map<string, string>): string {
  if (replacements.size === 0) return html;
  return html.replace(/<img\s+src="([^"]*)"/g, (match, src: string) => {
    const replacement = replacements.get(decodeHtml(src));
    return replacement ? `<img src="${replacement}"` : match;
  });
}

function decodeHtml(s: string): string {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

export function toBase64(bytes: Uint8Array): string {
  if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64");
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}
