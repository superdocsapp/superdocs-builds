import type { HttpRequest, HttpResponse, Transport } from "./client";

/** `fetch`-backed transport, for the CLI and for integration tests. */
export const nodeTransport: Transport = async (req: HttpRequest): Promise<HttpResponse> => {
  const res = await fetch(req.url, {
    method: req.method,
    headers: req.headers,
    body: req.body as BodyInit | undefined,
  });
  const buffer = await res.arrayBuffer();
  const headers: Record<string, string> = {};
  res.headers.forEach((value, key) => {
    headers[key.toLowerCase()] = value;
  });
  return {
    status: res.status,
    headers,
    text: safeText(buffer, headers["content-type"] ?? ""),
    arrayBuffer: buffer,
  };
};

/**
 * Binary exports must not be forced through a UTF-8 decoder just to populate
 * `text`. Decoding a .docx as text is harmless but wasteful at 40 MB, and the
 * decoded string is never read for those responses.
 */
function safeText(buffer: ArrayBuffer, contentType: string): string {
  const isBinary =
    /^(application\/(vnd|octet|pdf|zip)|image\/)/i.test(contentType) &&
    !/json|text|xml/i.test(contentType);
  if (isBinary) return "";
  return new TextDecoder("utf-8").decode(buffer);
}
