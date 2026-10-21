import { requestUrl } from "obsidian";
import type { HttpRequest, HttpResponse, Transport } from "./client";

/**
 * Obsidian's `requestUrl` rather than `fetch`.
 *
 * `fetch` from a plugin runs in the renderer and is subject to CORS, which the
 * SuperDocs API has no reason to allow for arbitrary Obsidian installs.
 * `requestUrl` goes through Electron's net stack and is the supported way for a
 * plugin to call a third-party API on desktop and mobile alike.
 *
 * It also does not throw on non-2xx when `throw: false` is set, which is what we
 * want — the client's own error mapping should see the status and the body.
 */
export const obsidianTransport: Transport = async (req: HttpRequest): Promise<HttpResponse> => {
  const res = await requestUrl({
    url: req.url,
    method: req.method,
    headers: req.headers,
    body: req.body,
    throw: false,
  });

  const headers: Record<string, string> = {};
  for (const [key, value] of Object.entries(res.headers ?? {})) {
    headers[key.toLowerCase()] = String(value);
  }

  return {
    status: res.status,
    headers,
    text: safeText(res),
    arrayBuffer: res.arrayBuffer,
  };
};

function safeText(res: { text?: string; arrayBuffer: ArrayBuffer; headers?: Record<string, string> }): string {
  const contentType = String(
    res.headers?.["content-type"] ?? res.headers?.["Content-Type"] ?? "",
  ).toLowerCase();
  const isBinary =
    /^(application\/(vnd|octet|pdf|zip)|image\/)/.test(contentType) &&
    !/json|text|xml/.test(contentType);
  if (isBinary) return "";
  // requestUrl only populates `.text` when it believes the body is text.
  if (typeof res.text === "string") return res.text;
  return new TextDecoder("utf-8").decode(res.arrayBuffer);
};
