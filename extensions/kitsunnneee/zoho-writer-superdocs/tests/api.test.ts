import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SigmaSuperDocsClient,
  getBodyEncoding,
  hasSessionApiKey,
  setBodyEncoding,
  setSessionApiKey,
  type WriterRequest,
} from "../src/api";

// The host's body field name is negotiated at runtime, so assertions read the
// body through whichever field carries it instead of pinning one name.
const bodyOf = (request?: WriterRequest): unknown => {
  if (!request) return undefined;
  if (request.payload !== undefined) return JSON.parse(request.payload);
  if (request.parameters !== undefined) return JSON.parse(request.parameters);
  return request.postBody;
};

const bodyFieldsOf = (request?: WriterRequest): string[] =>
  ["payload", "parameters", "postBody"].filter(
    (field) => (request as Record<string, unknown> | undefined)?.[field] !== undefined,
  );

const recorder = () => {
  const requests: WriterRequest[] = [];
  const client = new SigmaSuperDocsClient(async (request) => {
    requests.push(request);
    return { ok: true };
  });
  return { client, requests };
};

describe("Sigma request contracts", () => {
  // The session key and fetch stub are module/global state; leaking either
  // would silently change the transport asserted by every later test.
  afterEach(() => {
    setSessionApiKey("");
    setBodyEncoding(undefined);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends upload and async chat through the named connection without credentials", async () => {
    const { client, requests } = recorder();
    await client.upload("<p>Selected</p>", "session-1");
    await client.startChat("session-1", "Tighten this");

    expect(requests[0]).toMatchObject({
      url: "https://api.superdocs.app/v1/documents/upload-base64",
      method: "POST",
      connectionLinkName: "superdocsapi",
    });
    const uploadPayload = bodyOf(requests[0]) as {
      filename: string;
      file_base64: string;
      session_id: string;
      return_html: boolean;
    };
    expect(uploadPayload).toMatchObject({
      filename: "writer-selection.html",
      session_id: "session-1",
      return_html: false,
    });
    const uploaded = uploadPayload.file_base64;
    expect(uploaded).toBe(btoa("<p>Selected</p>"));
    expect(requests[1]).toMatchObject({
      url: "https://api.superdocs.app/v1/chat/async",
      method: "POST",
      connectionLinkName: "superdocsapi",
    });
    expect(bodyOf(requests[1])).toEqual({
        session_id: "session-1",
        message: "Tighten this",
        approval_mode: "ask_every_time",
        response_mode: "full",
        async_mode: true,
    });
    // Only keys implemented by the returned v3 client may be sent.
    const allowed = new Set([
      "url",
      "method",
      "connectionLinkName",
      "headers",
      "postBody",
      "payload",
      "parameters",
    ]);
    for (const request of requests) {
      expect(Object.keys(request).filter((key) => !allowed.has(key))).toEqual([]);
      // Sending several body fields at once is what the host rejects outright.
      expect(bodyFieldsOf(request)).toHaveLength(1);
    }
    expect(JSON.stringify(requests)).not.toContain("Authorization");
    expect(JSON.stringify(requests)).not.toMatch(/\bsk_[A-Za-z0-9_-]{12,}/);
  });

  it("probes the connection with the non-billable sessions endpoint", async () => {
    const { client, requests } = recorder();
    await client.checkConnection();

    expect(requests[0]).toMatchObject({
      url: "https://api.superdocs.app/v1/sessions",
      method: "GET",
      connectionLinkName: "superdocsapi",
    });
  });

  it("probes a verified public endpoint without a connection", async () => {
    const { client, requests } = recorder();
    await client.checkTransport();

    expect(requests[0]?.url).toBe("https://api.superdocs.app/health");
    expect(requests[0]?.connectionLinkName).toBeUndefined();
  });

  it("uses exact approval and continue request shapes", async () => {
    const { client, requests } = recorder();
    await client.approve("session-1", {
      job_id: "job-1",
      approved: false,
      changes: [
        { change_id: "c1", approved: true },
        { change_id: "c2", approved: false },
      ],
    });
    await client.continueChat("session-1", "job-1", true);

    expect(requests[0]).toMatchObject({
      url: "https://api.superdocs.app/v1/chat/session-1/approve",
      method: "POST",
    });
    expect(bodyOf(requests[0])).toEqual({
      job_id: "job-1",
      approved: false,
      changes: [
        { change_id: "c1", approved: true },
        { change_id: "c2", approved: false },
      ],
    });
    expect(requests[1]).toMatchObject({
      url: "https://api.superdocs.app/v1/chat/session-1/continue",
      method: "POST",
    });
    expect(bodyOf(requests[1])).toEqual({
      job_id: "job-1",
      continue: true,
    });
  });

  it("bypasses the connection and sends an explicit Bearer header when a session key is set", async () => {
    const { client, requests } = recorder();
    setSessionApiKey("  sk_livekey123  ");
    expect(hasSessionApiKey()).toBe(true);

    await client.upload("<p>Selected</p>", "session-1");

    // The connection is not referenced at all once a key is supplied.
    expect(requests[0]?.connectionLinkName).toBeUndefined();
    expect(requests[0]?.headers?.Authorization).toBe("Bearer sk_livekey123");
    // Content-Type must survive alongside the injected header.
    expect(requests[0]?.headers?.["Content-Type"]).toBe("application/json");
  });

  it("treats a blank key as absent and returns to the named connection", async () => {
    const { client, requests } = recorder();
    setSessionApiKey("   ");
    expect(hasSessionApiKey()).toBe(false);

    await client.checkConnection();

    expect(requests[0]?.connectionLinkName).toBe("superdocsapi");
    expect(requests[0]?.headers?.Authorization).toBeUndefined();
  });

  it("falls back to a direct browser call when Sigma rejects the authorized relay", async () => {
    setSessionApiKey("sk_livekey123");
    const relay = vi.fn(async () => {
      throw { message: "failed" };
    });
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new SigmaSuperDocsClient(relay);

    await expect(client.checkConnection()).resolves.toEqual({ ok: true });

    expect(relay).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://api.superdocs.app/v1/sessions",
    );
    const init = fetchMock.mock.calls[0]?.[1];
    expect((init?.headers as Record<string, string>).Authorization).toBe(
      "Bearer sk_livekey123",
    );
  });

  it("reports both failures when the relay and the direct call each fail", async () => {
    setSessionApiKey("sk_livekey123");
    const relay = vi.fn(async () => {
      throw { message: "failed" };
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("nope", { status: 401 })),
    );
    const client = new SigmaSuperDocsClient(relay);

    await expect(client.checkConnection()).rejects.toThrow(
      /Sigma relay rejected the authorized request \(failed\).*direct browser call also failed \(.*401.*\)/s,
    );
  });

  it("negotiates past body fields the host drops, then reuses the winner", async () => {
    const seen: WriterRequest[] = [];
    // Mimics the observed live host: bodyless GETs pass, and a POST is rejected
    // unless the body arrives in `parameters`.
    const client = new SigmaSuperDocsClient(async (request) => {
      seen.push(request);
      if (request.method === "POST" && request.parameters === undefined) {
        throw { message: "failed" };
      }
      return { ok: true };
    });

    await client.upload("<p>a</p>", "session-1");

    expect(seen.map((request) => bodyFieldsOf(request)[0])).toEqual([
      "payload",
      "postBody",
      "parameters",
    ]);
    expect(getBodyEncoding()).toBe("parameters");

    // The winning encoding is reused without re-probing the rejected ones.
    seen.length = 0;
    await client.startChat("session-1", "Tighten this");
    expect(seen).toHaveLength(1);
    expect(bodyFieldsOf(seen[0])).toEqual(["parameters"]);
    expect(bodyOf(seen[0])).toMatchObject({ message: "Tighten this" });
  });

  it("reports every rejected encoding when the host accepts no body field", async () => {
    const client = new SigmaSuperDocsClient(async () => {
      throw { message: "failed" };
    });

    await expect(client.upload("<p>a</p>", "session-1")).rejects.toThrow(
      /No request body encoding was accepted.*payload.*postBody.*parameters/s,
    );
    expect(getBodyEncoding()).toBeUndefined();
  });

  // A real .docx is a zip: it starts with "PK\x03\x04" and ends with an
  // end-of-central-directory record. Both are required, so a truncated or
  // text-mangled body cannot pass as a document.
  const ZIP_BYTES = new Uint8Array([
    0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00, 0x08, 0x00, 0x50, 0x4b,
    0x05, 0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
  ]);
  const ZIP_BASE64 = btoa(String.fromCharCode(...ZIP_BYTES));

  // Export makes two calls at most: .docx first, then HTML if the .docx did not
  // survive. Keying off the requested format exercises that real sequence.
  const exportClient = (docx: unknown, html: unknown = "<p>approved</p>") =>
    new SigmaSuperDocsClient(async (request) => {
      const body = bodyOf(request) as { format?: string } | undefined;
      return body?.format === "html" ? html : docx;
    });

  it("decodes a base64 docx relayed as a bare string", async () => {
    setBodyEncoding("payload");
    const result = await exportClient(ZIP_BASE64).exportDocument("session-1");

    expect(new Uint8Array(await result.blob.arrayBuffer())).toEqual(ZIP_BYTES);
    expect(result.format).toBe("docx");
    expect(result.filename).toBe("superdocs-reviewed-selection.docx");
    expect(result.blob.type).toContain("wordprocessingml.document");
    expect(result.note).toBeUndefined();
  });

  it("finds a base64 docx nested in a relay envelope", async () => {
    setBodyEncoding("payload");
    const result = await exportClient({
      status: 200,
      data: { content: ZIP_BASE64 },
    }).exportDocument("session-1");

    expect(new Uint8Array(await result.blob.arrayBuffer())).toEqual(ZIP_BYTES);
  });

  it("finds the docx inside Sigma's observed {message,data,http_statuscode} envelope", async () => {
    setBodyEncoding("payload");
    const result = await exportClient({
      message: "success",
      data: ZIP_BASE64,
      http_statuscode: 200,
    }).exportDocument("session-1");

    expect(new Uint8Array(await result.blob.arrayBuffer())).toEqual(ZIP_BYTES);
  });

  it("recovers binary relayed verbatim as a latin1 string", async () => {
    setBodyEncoding("payload");
    const result = await exportClient({
      message: "success",
      data: String.fromCharCode(...ZIP_BYTES),
      http_statuscode: 200,
    }).exportDocument("session-1");

    expect(new Uint8Array(await result.blob.arrayBuffer())).toEqual(ZIP_BYTES);
  });

  it("recovers a byte array that a postMessage round-trip turned into indexed keys", async () => {
    setBodyEncoding("payload");
    const indexed = Object.fromEntries(
      Array.from(ZIP_BYTES).map((byte, index) => [String(index), byte]),
    );
    const result = await exportClient({
      message: "success",
      data: indexed,
      http_statuscode: 200,
    }).exportDocument("session-1");

    expect(new Uint8Array(await result.blob.arrayBuffer())).toEqual(ZIP_BYTES);
  });

  it("rejects a zip whose central directory did not survive the relay", async () => {
    setBodyEncoding("payload");
    // Correct signature, truncated body: exactly what a half-relayed file looks
    // like, and it must not be offered as a document.
    const truncated = btoa(
      String.fromCharCode(0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00),
    );
    const result = await exportClient(truncated).exportDocument("session-1");

    expect(result.format).toBe("html");
  });

  // The real host behaviour: Zoho decodes the response as UTF-8, which replaces
  // every byte above 0x7f, so the archive cannot be reconstructed at all.
  it("falls back to HTML and names the byte loss when the host mangles the docx", async () => {
    setBodyEncoding("payload");
    const mangled = `PK${"�".repeat(40)}`;
    const result = await exportClient(
      { message: "success", data: mangled, http_statuscode: 200 },
      { message: "success", data: "<p>approved</p>", http_statuscode: 200 },
    ).exportDocument("session-1");

    expect(result.format).toBe("html");
    expect(result.filename).toBe("superdocs-reviewed-selection.html");
    expect(await result.blob.text()).toBe("<p>approved</p>");
    expect(result.note).toMatch(/replaced 40 of 44 bytes/);
    expect(result.note).toMatch(/exported as HTML instead/);
  });

  it("fails loudly when neither the docx nor the HTML fallback yields content", async () => {
    setBodyEncoding("payload");
    const result = exportClient(
      { unexpected: true, note: "no file anywhere" },
      { data: "" },
    ).exportDocument("session-1");

    await expect(result).rejects.toThrow(
      /object\{unexpected:boolean, note:string\(16\).*HTML fallback returned no content/s,
    );
  });

  it("encodes malicious path values instead of changing request structure", async () => {
    const { client, requests } = recorder();
    const malicious = "../../x?<script>alert(1)</script>";
    await client.getJob(malicious);
    await client.continueChat(malicious, "job-1", false);

    expect(requests[0]?.url).toBe(
      "https://api.superdocs.app/v1/jobs/..%2F..%2Fx%3F%3Cscript%3Ealert(1)%3C%2Fscript%3E",
    );
    expect(requests[1]?.url).toBe(
      "https://api.superdocs.app/v1/chat/..%2F..%2Fx%3F%3Cscript%3Ealert(1)%3C%2Fscript%3E/continue",
    );
  });
});
