import type { ApprovalPayload, ExportResult, SuperDocsPort } from "./types";

const API_BASE = "https://api.superdocs.app";
const CONNECTION = "superdocsapi";

// Contract implemented by the service client returned from SigmaSDK.WRITER.init.
// Established by inspecting the live wire payload, not from documentation: the
// client keys the HTTP verb off `method` and silently defaults to "GET" when it
// is absent, so Zoho support's `type` field belongs to some other facade.
//
// The body field name is not documented anywhere I could find, and bodyless GETs
// succeed while POSTs are rejected, which is what a dropped body looks like. The
// candidates below are therefore negotiated once at runtime rather than guessed.
// Exactly one of them is ever set on a request.
export interface WriterRequest {
  url: string;
  method: "GET" | "POST";
  connectionLinkName?: string;
  headers?: Record<string, string>;
  postBody?: unknown;
  payload?: string;
  parameters?: string;
}

// Ordered by likelihood: `payload` is what this repository used before a support
// reply redirected it to `postBody`, and that same reply proved wrong about the
// verb field, so its body field is suspect too.
export type BodyEncoding = "payload" | "postBody" | "parameters";

const BODY_ENCODINGS: readonly BodyEncoding[] = [
  "payload",
  "postBody",
  "parameters",
];

let negotiatedEncoding: BodyEncoding | undefined;

// Exposed for tests and for reporting which encoding the live host accepted.
export const getBodyEncoding = (): BodyEncoding | undefined =>
  negotiatedEncoding;

export const setBodyEncoding = (encoding?: BodyEncoding): void => {
  negotiatedEncoding = encoding;
};

const encodeBody = (
  base: WriterRequest,
  body: unknown,
  encoding: BodyEncoding,
): WriterRequest =>
  encoding === "postBody"
    ? { ...base, postBody: body }
    : { ...base, [encoding]: JSON.stringify(body) };

export interface SigmaWriterClient {
  dispatch(event: string, options: Record<string, unknown>): Promise<unknown>;
  request(options: WriterRequest): Promise<unknown>;
}

interface SigmaWriterSdk {
  init(onReady?: () => void): SigmaWriterClient;
}

declare global {
  interface Window {
    SigmaSDK?: { WRITER: SigmaWriterSdk };
  }
}

const writerSdk = (): SigmaWriterSdk => {
  const sdk = window.SigmaSDK?.WRITER;
  if (!sdk) {
    throw new Error("Sigma SDK v3 is unavailable. Open this build inside Zoho Writer.");
  }
  return sdk;
};

let activeWriterClient: SigmaWriterClient | undefined;
let writerReady: Promise<void> | undefined;

export const initializeSigma = (): Promise<void> => {
  if (writerReady) return writerReady;

  writerReady = new Promise<void>((resolve, reject) => {
    try {
      // The live v3 SDK returns the service client synchronously. Its callback
      // fires only after the parent Writer frame registers this widget.
      activeWriterClient = writerSdk().init(resolve);
    } catch (error) {
      writerReady = undefined;
      reject(error);
    }
  });
  return writerReady;
};

export const getSigmaWriterClient = (): SigmaWriterClient => {
  if (!activeWriterClient) {
    throw new Error("Sigma Writer SDK has not finished initialization.");
  }
  return activeWriterClient;
};

export type WriterRequester = (options: WriterRequest) => Promise<unknown>;

// Sigma's named connection is the preferred transport: the key then never
// reaches the browser. In this workspace that path fails for every request
// while an identical connectionless request to the same host succeeds, so a
// user-supplied key is offered as an explicit, documented fallback. The key is
// held in memory only and is never written to browser storage.
let sessionApiKey: string | undefined;

export const setSessionApiKey = (key: string): void => {
  const trimmed = key.trim();
  sessionApiKey = trimmed.length > 0 ? trimmed : undefined;
};

export const hasSessionApiKey = (): boolean => Boolean(sessionApiKey);

// Used only when Sigma refuses to relay a client-supplied Authorization
// header. The widget origin is sandboxed, so this depends on SuperDocs
// sending permissive CORS headers.
const directRequest = async (
  options: WriterRequest,
  wantsBlob: boolean,
): Promise<unknown> => {
  // Whichever field the negotiation put the body in, the wire format here is
  // always plain JSON.
  const body =
    options.payload ??
    options.parameters ??
    (options.postBody === undefined
      ? undefined
      : JSON.stringify(options.postBody));
  const response = await fetch(options.url, {
    method: options.method,
    headers: options.headers,
    body,
  });
  if (!response.ok) {
    throw new Error(
      `Direct browser request failed with status ${response.status}.`,
    );
  }
  return wantsBlob ? await response.blob() : await response.json();
};

const encodeBase64 = (text: string): string => {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
};

// Local, dependency-free message extraction. Sigma rejects with bare objects
// such as {message:"failed"}, so the shape is read defensively.
const briefError = (value: unknown): string => {
  if (value instanceof Error && value.message) return value.message;
  if (typeof value === "object" && value !== null) {
    const message = (value as Record<string, unknown>).message;
    if (typeof message === "string" && message) return message;
  }
  return "no detail";
};

// Raised when the export call itself succeeded but the relayed body could not
// be turned into a verified file. Distinct from a transport failure so the UI
// does not blame the connection for a response-decoding problem.
export class UnsupportedFileResponseError extends Error {
  constructor(shape: string) {
    super(
      `Export completed, but the relayed file response could not be decoded (${shape}).`,
    );
    this.name = "UnsupportedFileResponseError";
  }
}

// Nested one level, because the useful detail is what the envelope's fields
// hold, not that the envelope exists.
const describeShape = (value: unknown, depth = 0): string => {
  if (value === null) return "null";
  if (value instanceof Blob) return `blob(${value.size}B)`;
  if (typeof value === "string") {
    return `string(${value.length})${
      value.length > 0 ? ` starting ${JSON.stringify(value.slice(0, 10))}` : ""
    }`;
  }
  if (typeof value !== "object") return typeof value;
  if (Array.isArray(value)) return `array(${value.length})`;
  const keys = Object.keys(value);
  if (depth >= 1) return `object{${keys.slice(0, 8).join(",")}}`;
  return `object{${keys
    .slice(0, 8)
    .map(
      (key) =>
        `${key}:${describeShape((value as Record<string, unknown>)[key], depth + 1)}`,
    )
    .join(", ")}}`;
};

const BASE64_STANDARD = /^[A-Za-z0-9+/]+={0,2}$/;
const BASE64_URLSAFE = /^[A-Za-z0-9\-_]+={0,2}$/;

const fromBase64 = (text: string): Uint8Array | undefined => {
  try {
    const binary = atob(text);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  } catch {
    return undefined;
  }
};

// Each candidate is tried in turn and only accepted if it proves to be a zip,
// so an over-broad search cannot produce a bogus file.
const decodings = (value: unknown): Uint8Array[] => {
  if (value instanceof ArrayBuffer) return [new Uint8Array(value)];
  if (value instanceof Uint8Array) return [value];

  if (typeof value === "string") {
    const results: Uint8Array[] = [];
    const cleaned = value.replace(/\s+/g, "");
    if (cleaned.length > 0) {
      if (BASE64_STANDARD.test(cleaned)) {
        const bytes = fromBase64(cleaned);
        if (bytes) results.push(bytes);
      } else if (BASE64_URLSAFE.test(cleaned)) {
        const bytes = fromBase64(cleaned.replace(/-/g, "+").replace(/_/g, "/"));
        if (bytes) results.push(bytes);
      }
    }
    // Binary relayed verbatim as a latin1 string.
    const raw = new Uint8Array(value.length);
    let inRange = value.length > 0;
    for (let index = 0; index < value.length; index += 1) {
      const code = value.charCodeAt(index);
      if (code > 0xff) {
        inRange = false;
        break;
      }
      raw[index] = code;
    }
    if (inRange) results.push(raw);
    return results;
  }

  // postMessage/JSON round-trips turn byte arrays into arrays or into objects
  // keyed by index.
  if (Array.isArray(value)) {
    if (value.every((entry) => typeof entry === "number")) {
      return [Uint8Array.from(value as number[])];
    }
    return [];
  }
  if (typeof value === "object" && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>);
    if (
      entries.length > 3 &&
      entries.every(
        ([key, entry]) => /^\d+$/.test(key) && typeof entry === "number",
      )
    ) {
      const bytes = new Uint8Array(entries.length);
      for (const [key, entry] of entries) {
        bytes[Number(key)] = entry as number;
      }
      return [bytes];
    }
  }
  return [];
};

// A .docx is a ZIP, so valid output always begins with "PK".
const isZip = (bytes: Uint8Array): boolean =>
  bytes.length > 3 && bytes[0] === 0x50 && bytes[1] === 0x4b;

// The leading signature only proves the first two bytes survived. A complete
// zip also ends with an end-of-central-directory record, which is what catches
// a file truncated or mangled in transit.
const hasCentralDirectory = (bytes: Uint8Array): boolean => {
  for (let index = bytes.length - 4; index >= 0; index -= 1) {
    if (
      bytes[index] === 0x50 &&
      bytes[index + 1] === 0x4b &&
      bytes[index + 2] === 0x05 &&
      bytes[index + 3] === 0x06
    ) {
      return true;
    }
  }
  return false;
};

// Counts characters the host's text decoding destroyed. Sigma decodes response
// bodies as UTF-8, so every byte a zip holds above 0x7f comes back as U+FFFD and
// the original value is gone; a recovered file would be silently corrupt.
const lostBytes = (value: string): number => {
  let lost = 0;
  for (let index = 0; index < value.length; index += 1) {
    if (value.charCodeAt(index) > 0xff) lost += 1;
  }
  return lost;
};

// Content-bearing fields are checked before any other string, because the
// observed envelope also carries a status word ("message":"success") that would
// otherwise be mistaken for the exported document.
const CONTENT_FIELDS = [
  "data",
  "body",
  "content",
  "html",
  "response",
  "responseText",
  "file",
  "fileContent",
] as const;

const asText = (response: unknown, depth = 0): string | undefined => {
  if (typeof response === "string") return response;
  if (depth < 4 && typeof response === "object" && response !== null) {
    const record = response as Record<string, unknown>;
    for (const field of CONTENT_FIELDS) {
      if (!(field in record)) continue;
      const text = asText(record[field], depth + 1);
      if (text !== undefined && text.length > 0) return text;
    }
    for (const value of Object.values(record)) {
      const text = asText(value, depth + 1);
      if (text !== undefined && text.length > 0) return text;
    }
  }
  return undefined;
};

// Walks the whole relay envelope rather than trusting particular field names,
// since the envelope shape is undocumented and has already changed once.
const findZipBytes = (value: unknown, depth = 0): Uint8Array | undefined => {
  for (const candidate of decodings(value)) {
    // Require a complete archive, not just the signature, so a mangled body is
    // never handed back as a document.
    if (isZip(candidate) && hasCentralDirectory(candidate)) return candidate;
  }
  if (depth >= 5) return undefined;
  const children = Array.isArray(value)
    ? value
    : typeof value === "object" && value !== null
      ? Object.values(value as Record<string, unknown>)
      : [];
  for (const child of children) {
    const bytes = findZipBytes(child, depth + 1);
    if (bytes) return bytes;
  }
  return undefined;
};

const asBlob = async (response: unknown): Promise<Blob> => {
  if (response instanceof Blob) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (isZip(bytes)) return response;
    throw new UnsupportedFileResponseError(
      `blob(${response.size}B) is not a zip`,
    );
  }
  const bytes = findZipBytes(response);
  if (!bytes) {
    // Name the specific cause when the host's text decoding is what destroyed
    // the file, rather than reporting a generic shape mismatch.
    const text = asText(response);
    if (text && text.startsWith("PK")) {
      const lost = lostBytes(text);
      if (lost > 0) {
        throw new UnsupportedFileResponseError(
          `the host relayed the archive as UTF-8 text and replaced ${lost} of ${text.length} bytes, so the .docx cannot be reconstructed`,
        );
      }
    }
    throw new UnsupportedFileResponseError(describeShape(response));
  }
  // Copy out of the view so the Blob owns exactly the decoded bytes.
  const buffer = bytes.buffer.slice(
    bytes.byteOffset,
    bytes.byteOffset + bytes.byteLength,
  ) as ArrayBuffer;
  return new Blob([buffer], {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
};

export class SigmaSuperDocsClient implements SuperDocsPort {
  constructor(
    private readonly requester: WriterRequester = (options) =>
      getSigmaWriterClient().request(options),
  ) {}

  // Without a session key the named connection is used unchanged. With one, the
  // Authorization header is supplied explicitly and the connection is not
  // referenced at all.
  private async request(
    spec: {
      url: string;
      method: "GET" | "POST";
      headers?: Record<string, string>;
      body?: unknown;
    },
    wantsBlob = false,
  ): Promise<unknown> {
    const base: WriterRequest = {
      url: spec.url,
      method: spec.method,
      ...(spec.headers ? { headers: spec.headers } : {}),
      ...(sessionApiKey
        ? {
            headers: {
              ...spec.headers,
              Authorization: `Bearer ${sessionApiKey}`,
            },
          }
        : { connectionLinkName: CONNECTION }),
    };

    if (spec.body === undefined) return this.send(base, wantsBlob);

    if (negotiatedEncoding) {
      return this.send(encodeBody(base, spec.body, negotiatedEncoding), wantsBlob);
    }

    // First bodied request of the session: find the field the host honours and
    // reuse it for every later call rather than re-probing.
    const failures: string[] = [];
    for (const encoding of BODY_ENCODINGS) {
      try {
        const result = await this.send(
          encodeBody(base, spec.body, encoding),
          wantsBlob,
        );
        negotiatedEncoding = encoding;
        return result;
      } catch (error) {
        failures.push(`${encoding}: ${briefError(error)}`);
      }
    }
    throw new Error(
      `No request body encoding was accepted (${failures.join("; ")}).`,
    );
  }

  private async send(
    options: WriterRequest,
    wantsBlob: boolean,
  ): Promise<unknown> {
    try {
      return await this.requester(options);
    } catch (relayError) {
      if (!sessionApiKey) throw relayError;
      // Sigma may refuse to relay a client-supplied Authorization header.
      try {
        return await directRequest(options, wantsBlob);
      } catch (directError) {
        throw new Error(
          `Sigma relay rejected the authorized request (${briefError(relayError)});` +
            ` the direct browser call also failed (${briefError(directError)}).`,
        );
      }
    }
  }

  // Sigma relays requests to its parent frame via postMessage, which is a poor
  // fit for multipart File uploads. The base64 endpoint keeps the payload JSON.
  async upload(html: string, sessionId: string): Promise<unknown> {
    return this.request({
      url: `${API_BASE}/v1/documents/upload-base64`,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: {
        filename: "writer-selection.html",
        file_base64: encodeBase64(html),
        session_id: sessionId,
        return_html: false,
      },
    });
  }

  // GET /v1/sessions is documented as non-billable, so it can verify the named
  // connection without spending an operation.
  checkConnection(): Promise<unknown> {
    return this.request({
      url: `${API_BASE}/v1/sessions`,
      method: "GET",
    });
  }

  // Public endpoint verified to return 200 without authentication. This
  // distinguishes Sigma transport/allowlist failure from connection failure.
  checkTransport(): Promise<unknown> {
    return this.requester({
      url: `${API_BASE}/health`,
      method: "GET",
    });
  }

  startChat(sessionId: string, instruction: string): Promise<unknown> {
    return this.request({
      url: `${API_BASE}/v1/chat/async`,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: {
        session_id: sessionId,
        message: instruction,
        approval_mode: "ask_every_time",
        response_mode: "full",
        async_mode: true,
      },
    });
  }

  getJob(jobId: string): Promise<unknown> {
    return this.request({
      url: `${API_BASE}/v1/jobs/${encodeURIComponent(jobId)}`,
      method: "GET",
    });
  }

  approve(sessionId: string, payload: ApprovalPayload): Promise<unknown> {
    return this.request({
      url: `${API_BASE}/v1/chat/${encodeURIComponent(sessionId)}/approve`,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
    });
  }

  continueChat(
    sessionId: string,
    jobId: string,
    shouldContinue: boolean,
  ): Promise<unknown> {
    return this.request({
      url: `${API_BASE}/v1/chat/${encodeURIComponent(sessionId)}/continue`,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: { job_id: jobId, continue: shouldContinue },
    });
  }

  // Exports are not billed, so .docx is attempted first and verified. The host
  // relay decodes bodies as UTF-8, which destroys a zip, so when that is what
  // happened the approved result is re-exported as HTML — a text format survives
  // the same relay byte for byte. Returning a broken .docx is not an option.
  async exportDocument(sessionId: string): Promise<ExportResult> {
    const exportCall = (format: "docx" | "html", wantsBlob: boolean) =>
      this.request(
        {
          url: `${API_BASE}/v1/documents/export`,
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: {
            session_id: sessionId,
            format,
            options: { filename: "superdocs-reviewed-selection" },
          },
        },
        wantsBlob,
      );

    let docxFailure: string;
    try {
      const blob = await asBlob(await exportCall("docx", true));
      return {
        blob,
        filename: "superdocs-reviewed-selection.docx",
        format: "docx",
      };
    } catch (error) {
      if (!(error instanceof UnsupportedFileResponseError)) throw error;
      docxFailure = error.message;
    }

    const html = asText(await exportCall("html", false));
    if (html === undefined || html.length === 0) {
      throw new UnsupportedFileResponseError(
        `${docxFailure}; the HTML fallback returned no content either`,
      );
    }
    return {
      blob: new Blob([html], { type: "text/html;charset=utf-8" }),
      filename: "superdocs-reviewed-selection.html",
      format: "html",
      note: `The .docx could not be delivered through the Writer host: ${docxFailure}. The approved result was exported as HTML instead, which crosses the same relay intact.`,
    };
  }
}
