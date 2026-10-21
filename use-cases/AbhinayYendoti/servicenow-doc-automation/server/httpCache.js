/**
 * Transfer-level concerns: compression and cache headers.
 *
 * The built bundle is ~209 KB of highly compressible text served on every cold
 * load, and Vite already fingerprints asset filenames, so both of these were
 * free wins that simply were not being taken.
 */

import compression from "compression";

/**
 * gzip, minus the event stream.
 *
 * Compression middleware buffers to fill a compression window, and a buffered
 * event stream is not an event stream — the reviewer would watch the model work
 * in silent bursts. Everything else compresses; the DOCX export is already a
 * zip and is left alone by the default filter.
 *
 * This is `compression` rather than something hand-rolled because the tricky
 * part is backpressure: `pipe` waits for `drain` on the response, but under a
 * naive wrapper it is the compressor that fills up, so the response never
 * drains and a large file transfer deadlocks partway through.
 */
export function httpCompression() {
  return compression({
    filter(request, response) {
      const type = String(response.getHeader("content-type") ?? "");
      if (type.startsWith("text/event-stream")) return false;
      return compression.filter(request, response);
    }
  });
}

/**
 * Cache headers for the built assets.
 *
 * Vite fingerprints asset filenames, so their contents can never change under a
 * given URL — those are safe to cache forever. `index.html` is the opposite: it
 * is the thing that points at the current fingerprints, so it must always be
 * revalidated or a deploy leaves browsers loading the previous bundle.
 */
export function staticCacheHeaders(response, filePath) {
  const fingerprinted =
    /\.(?:js|css|woff2?|png|jpg|jpeg|svg|webp|ico)$/iu.test(filePath) &&
    /[.-][A-Za-z0-9_-]{8,}\./u.test(filePath);

  response.setHeader(
    "Cache-Control",
    fingerprinted ? "public, max-age=31536000, immutable" : "no-cache"
  );
}
