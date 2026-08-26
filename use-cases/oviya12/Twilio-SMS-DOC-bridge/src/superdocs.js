import { createHash, randomUUID } from "node:crypto";
import { promises as dns } from "node:dns";
import path from "node:path";
import { promises as fs } from "node:fs";

const PRIVATE_V4 = /^(127\.|10\.|192\.168\.|169\.254\.|0\.)|^172\.(1[6-9]|2\d|3[0-1])\./;

function assertPublicUrl(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" || !url.hostname) throw new Error("Document reference must be a public HTTPS URL.");
  if (url.hostname === "localhost" || PRIVATE_V4.test(url.hostname) || url.hostname === "::1") {
    throw new Error("Document reference must not point to a private host.");
  }
  return url;
}

async function downloadPublicDocument(reference, maxBytes) {
  let url = assertPublicUrl(reference);
  for (let redirect = 0; redirect <= 3; redirect += 1) {
    const addresses = await dns.lookup(url.hostname, { all: true });
    if (addresses.some(({ address }) => PRIVATE_V4.test(address) || address === "::1" || address.startsWith("fc") || address.startsWith("fd") || address.startsWith("fe80"))) {
      throw new Error("Document reference resolved to a private network address.");
    }
    const response = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(20_000) });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("location");
      if (!location) throw new Error("Document link redirected without a location.");
      url = assertPublicUrl(new URL(location, url).toString());
      continue;
    }
    if (!response.ok) throw new Error(`Could not download document (${response.status}).`);
    const declaredSize = Number(response.headers.get("content-length") || 0);
    if (declaredSize > maxBytes) throw new Error("Document is larger than the allowed size.");
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.length > maxBytes) throw new Error("Document is larger than the allowed size.");
    return { bytes, filename: path.basename(url.pathname) || "document.bin", contentType: response.headers.get("content-type") || "application/octet-stream" };
  }
  throw new Error("Too many redirects while downloading the document.");
}

export class SuperDocsService {
  constructor({ apiKey, baseUrl, publicBaseUrl, resultsDir, maxDocumentBytes }) {
    this.apiKey = apiKey;
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.publicBaseUrl = publicBaseUrl.replace(/\/$/, "");
    this.resultsDir = resultsDir;
    this.maxDocumentBytes = maxDocumentBytes;
  }

  async request(endpoint, options = {}) {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers: { Authorization: `Bearer ${this.apiKey}`, ...options.headers },
      signal: AbortSignal.timeout(90_000)
    });
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 500);
      throw new Error(`SuperDocs ${endpoint} failed (${response.status}): ${detail}`);
    }
    return response;
  }

  async run({ messageSid, action, reference, instruction, format }) {
    const sessionId = `sms-${createHash("sha256").update(messageSid).digest("hex").slice(0, 24)}`;
    if (action === "EDIT") {
      const document = await downloadPublicDocument(reference, this.maxDocumentBytes);
      const form = new FormData();
      form.set("file", new Blob([document.bytes], { type: document.contentType }), document.filename);
      form.set("session_id", sessionId);
      await this.request("/v1/documents/upload", { method: "POST", body: form });
    }

    const chatPayload = {
      session_id: sessionId,
      message: instruction,
      approval_mode: "approve_all",
      response_mode: "full"
    };
    if (action === "CREATE") {
      chatPayload.document_html = "<main><h1>New document</h1><p></p></main>";
    }
    const chat = await (await this.request("/v1/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(chatPayload)
    })).json();

    const exportResponse = await this.request("/v1/documents/export", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: chat.session_id || sessionId, format, options: { filename: `superdocs-${messageSid}.${format}` } })
    });
    return this.persistExport(exportResponse, messageSid, format);
  }

  async persistExport(response, messageSid, format) {
    const type = response.headers.get("content-type") || "";
    if (type.includes("application/json")) {
      const body = await response.json();
      const link = body.url || body.download_url || body.downloadUrl;
      if (typeof link === "string" && /^https:\/\//.test(link)) return link;
      throw new Error("SuperDocs export returned JSON without a downloadable HTTPS link.");
    }
    const filename = `${randomUUID()}-${messageSid}.${format}`;
    await fs.mkdir(this.resultsDir, { recursive: true });
    await fs.writeFile(path.join(this.resultsDir, filename), Buffer.from(await response.arrayBuffer()));
    return `${this.publicBaseUrl}/files/${encodeURIComponent(filename)}`;
  }
}
