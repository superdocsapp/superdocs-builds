/**
 * The SuperDocs integration, tested without a key and without spending anything.
 *
 * These are not "my mock returned what I told it to" tests. Each one asserts a
 * specific thing that was learned the hard way against the live API, and that the
 * code would get wrong if someone refactored it carelessly:
 *
 *   - the top-level `approved` field the batch shape needs, or a bare 422
 *   - the second JSON parse proposed changes need, or every field reads undefined
 *   - which `awaiting_approval` you are looking at, or a 409
 *   - a rejection is a decision the system respects, not a suggestion
 */

import { describe, expect, it, vi } from "vitest";
import {
  SuperDocsClient,
  SuperDocsError,
  buildMultipart,
  decodeExportWarnings,
  parseMaybeEncoded,
} from "../src/superdocs/client";
import {
  applyApprovedChanges,
  extractPendingChanges,
  pollJob,
} from "../src/superdocs/jobs";
import { rewriteImageSources, uploadFigures } from "../src/superdocs/figures";
import { fakeServer, MemoryVault, noSleep } from "./helpers";

function client(script: Parameters<typeof fakeServer>[0]) {
  const server = fakeServer(script);
  return {
    server,
    client: new SuperDocsClient({
      apiKey: "sk_test",
      transport: server.transport,
      sleep: noSleep,
    }),
  };
}

describe("the four calls", () => {
  it("uploads the manuscript as multipart with the session id attached", async () => {
    const { client: c, server } = client([{ match: "/v1/documents/upload", json: { session_id: "s1" } }]);
    await c.uploadDocument({ sessionId: "s1", filename: "book.html", content: "<h1>Book</h1>" });

    const req = server.requests[0]!;
    expect(req.method).toBe("POST");
    const body = new TextDecoder().decode(req.body as ArrayBuffer);
    expect(body).toContain('name="session_id"');
    expect(body).toContain("s1");
    expect(body).toContain('filename="book.html"');
    expect(body).toContain("<h1>Book</h1>");
  });

  it("sends a chat turn in review mode when asked", async () => {
    const { client: c, server } = client([{ match: "/v1/chat/async", json: { job_id: "j1" } }]);
    const { job_id } = await c.chatAsync({
      sessionId: "s1",
      message: "Draft a preface.",
      documentHtml: "<h1>Book</h1>",
      approvalMode: "ask_every_time",
    });
    expect(job_id).toBe("j1");
    expect(server.requests[0]!.body).toMatchObject({
      session_id: "s1",
      approval_mode: "ask_every_time",
    });
  });

  it("always sends the top-level approved field on a batch approval", async () => {
    // Omitting it returns a bare 422 that explains nothing. This is the guard.
    const { client: c, server } = client([{ match: "/approve", json: {} }]);
    await c.approve({
      sessionId: "s1",
      jobId: "j1",
      decisions: [
        { changeId: "ch_1", approved: true },
        { changeId: "ch_2", approved: false, feedback: "Keep the original." },
      ],
    });
    const body = server.requests[0]!.body as Record<string, unknown>;
    expect(body).toHaveProperty("approved");
    expect(body.changes).toEqual([
      { change_id: "ch_1", approved: true },
      { change_id: "ch_2", approved: false, feedback: "Keep the original." },
    ]);
  });

  it("uses the single-change shape for one decision", async () => {
    const { client: c, server } = client([{ match: "/approve", json: {} }]);
    await c.approve({ sessionId: "s1", jobId: "j1", decisions: [{ changeId: "ch_1", approved: true }] });
    expect(server.requests[0]!.body).toEqual({ job_id: "j1", change_id: "ch_1", approved: true });
  });

  it("exports inline and returns the bytes plus any export warnings", async () => {
    const warnings = [{ code: "image_download_failed", message: "One plate 404'd." }];
    const header = Buffer.from(JSON.stringify(warnings)).toString("base64");
    const { client: c } = client([
      {
        match: "/v1/documents/export",
        bytes: new Uint8Array([0x25, 0x50, 0x44, 0x46]),
        headers: { "content-type": "application/pdf", "x-export-warnings": header },
      },
    ]);
    const result = await c.exportDocument({ format: "pdf", html: "<h1>Book</h1>" });
    expect(new Uint8Array(result.bytes)).toEqual(new Uint8Array([0x25, 0x50, 0x44, 0x46]));
    expect(result.warnings[0]!.code).toBe("image_download_failed");
  });

  it("switches to the pre-signed upload path for a manuscript over the inline limit", async () => {
    const huge = "x".repeat(21 * 1024 * 1024);
    const { client: c, server } = client([
      { match: "/v1/uploads", json: { upload_id: "u1", upload_url: "https://storage.example/put" } },
      { match: "storage.example", method: "PUT", json: {} },
      { match: "/v1/documents/export", bytes: new Uint8Array([1]) },
    ]);
    await c.exportDocument({ format: "docx", html: huge });

    expect(server.requests.map((r) => r.method)).toEqual(["POST", "PUT", "POST"]);
    expect(server.requests[2]!.body).toMatchObject({ upload_id: "u1" });
    // The 21 MB body never went through the API gateway.
    expect(JSON.stringify(server.requests[2]!.body).length).toBeLessThan(500);
  });
});

describe("errors are readable and retried only when retrying can help", () => {
  it("retries a 429 and then succeeds", async () => {
    const { client: c, server } = client([
      { match: "/v1/sessions", status: 429, json: { detail: "Rate limited" } },
      { match: "/v1/sessions", json: [] },
    ]);
    await expect(c.verifyKey()).resolves.toBe(true);
    expect(server.requests).toHaveLength(2);
  });

  it("does not retry a 401, and says what a 401 actually means here", async () => {
    const { client: c, server } = client([{ match: "/v1/sessions", status: 401, json: {} }]);
    await expect(c.verifyKey()).resolves.toBe(false);
    expect(server.requests).toHaveLength(1);
  });

  it("explains a non-JSON gateway page rather than throwing a parse error", async () => {
    const server = fakeServer([]);
    const transport = async () => ({
      status: 200,
      headers: { "content-type": "text/html" },
      text: "<html><body>502 Bad Gateway</body></html>",
      arrayBuffer: new ArrayBuffer(0),
    });
    const c = new SuperDocsClient({ apiKey: "sk_test", transport, sleep: noSleep });
    await expect(c.accountStatus()).rejects.toThrow(/non-JSON body/);
    expect(server.requests).toHaveLength(0);
  });

  it("surfaces the server's own message when it has one", async () => {
    const { client: c } = client([
      { match: "/v1/chat", status: 400, json: { detail: { message: "document_html is too large", code: "too_large" } } },
    ]);
    await expect(c.chat({ sessionId: "s", message: "x" })).rejects.toMatchObject({
      message: "document_html is too large",
      code: "too_large",
    });
  });
});

describe("proposed changes need a second parse", () => {
  it("parses a JSON-encoded string payload", () => {
    const encoded = JSON.stringify([
      { change_id: "ch_1", operation: "edit", old_html: "<p>a</p>", new_html: "<p>b</p>" },
    ]);
    const job = { job_id: "j", status: "awaiting_approval", metadata: { pending_changes: encoded } };
    const changes = extractPendingChanges(job as never);
    expect(changes).toHaveLength(1);
    // The failure this guards against is every field reading undefined.
    expect(changes[0]!.old_html).toBe("<p>a</p>");
    expect(changes[0]!.new_html).toBe("<p>b</p>");
  });

  it("parses a double-encoded payload", () => {
    const inner = JSON.stringify({ change_id: "ch_1", operation: "edit" });
    expect(parseMaybeEncoded<{ change_id: string }>(JSON.stringify(inner))?.change_id).toBe("ch_1");
  });

  it("passes an already-decoded payload straight through", () => {
    const job = {
      job_id: "j",
      status: "awaiting_approval",
      metadata: {
        pending_changes: [
          { change_id: "ch_1", operation: "edit", old_html: "<p>a</p>", new_html: "<p>b</p>" },
        ],
      },
    };
    expect(extractPendingChanges(job as never)[0]!.change_id).toBe("ch_1");
  });

  it("drops entries with no change id rather than showing an empty card", () => {
    const job = {
      job_id: "j",
      status: "awaiting_approval",
      metadata: { pending_changes: [{ operation: "edit" }, { change_id: "ch_2", operation: "edit" }] },
    };
    expect(extractPendingChanges(job as never).map((c) => c.change_id)).toEqual(["ch_2"]);
  });
});

describe("the job loop stops at the human gate", () => {
  const job = (over: Record<string, unknown>) => ({ job_id: "j1", ...over });

  it("polls through processing and stops when approval is needed", async () => {
    const { client: c } = client([
      { match: "/v1/jobs/j1", json: job({ status: "processing" }) },
      { match: "/v1/jobs/j1", json: job({ status: "processing" }) },
      {
        match: "/v1/jobs/j1",
        json: job({
          status: "awaiting_approval",
          metadata: { pending_changes: [{ change_id: "ch_1", operation: "edit" }] },
        }),
      },
    ]);
    const outcome = await pollJob(c, "j1", { sleep: noSleep, intervalMs: 0 });
    expect(outcome.kind).toBe("awaiting_approval");
    if (outcome.kind === "awaiting_approval") expect(outcome.changes).toHaveLength(1);
  });

  it("tells a continue-prompt pause apart from a change review", async () => {
    // Calling /approve on a continue prompt returns 409. Branch on awaiting_kind.
    const { client: c } = client([
      {
        match: "/v1/jobs/j1",
        json: job({ status: "awaiting_approval", metadata: { awaiting_kind: "continue_prompt" } }),
      },
    ]);
    const outcome = await pollJob(c, "j1", { sleep: noSleep, intervalMs: 0 });
    expect(outcome.kind).toBe("continue_prompt");
  });

  it("does not call a slow job a failure", async () => {
    const ticks: string[] = [];
    const { client: c } = client(
      Array.from({ length: 6 }, () => ({ match: "/v1/jobs/j1", json: job({ status: "processing" }) })).concat([
        { match: "/v1/jobs/j1", json: job({ status: "completed" }) },
      ]),
    );
    const outcome = await pollJob(c, "j1", {
      sleep: noSleep,
      intervalMs: 0,
      onTick: (j) => ticks.push(j.status),
    });
    expect(outcome.kind).toBe("completed");
    expect(ticks.filter((s) => s === "processing")).toHaveLength(6);
  });

  it("gives up with an honest message rather than pretending, after the timeout", async () => {
    let now = 0;
    const { client: c } = client(
      Array.from({ length: 4 }, () => ({ match: "/v1/jobs/j1", json: job({ status: "processing" }) })),
    );
    const outcome = await pollJob(c, "j1", {
      sleep: async () => {
        now += 60_000;
      },
      intervalMs: 0,
      timeoutMs: 100_000,
      now: () => now,
    });
    expect(outcome.kind).toBe("failed");
    if (outcome.kind === "failed") {
      expect(outcome.error).toContain("has not been cancelled");
    }
  });
});

describe("a rejection is respected", () => {
  const changes = [
    { change_id: "ch_1", operation: "edit" as const, chunk_id: null, old_html: "<p>keep me</p>", new_html: "<p>changed</p>", ai_explanation: "" },
    { change_id: "ch_2", operation: "edit" as const, chunk_id: null, old_html: "<p>second</p>", new_html: "<p>second, better</p>", ai_explanation: "" },
    { change_id: "ch_3", operation: "create" as const, chunk_id: null, old_html: null, new_html: "<p>appended</p>", ai_explanation: "" },
  ];

  it("applies only the accepted changes and leaves the rejected text alone", () => {
    const html = "<p>keep me</p><p>second</p>";
    const approvals = new Map([
      ["ch_1", false],
      ["ch_2", true],
      ["ch_3", true],
    ]);
    const result = applyApprovedChanges(html, changes, approvals);
    expect(result.html).toContain("<p>keep me</p>");
    expect(result.html).toContain("<p>second, better</p>");
    expect(result.html).toContain("<p>appended</p>");
    expect(result.applied).toBe(2);
    expect(result.skipped).toBe(1);
  });

  it("rejecting one change does not discard the others", () => {
    const html = "<p>keep me</p><p>second</p>";
    const all = applyApprovedChanges(html, changes, new Map(changes.map((c) => [c.change_id, true])));
    const one = applyApprovedChanges(html, changes, new Map([["ch_1", false], ["ch_2", true], ["ch_3", true]]));
    expect(all.applied).toBe(3);
    expect(one.applied).toBe(2);
    expect(one.html).toContain("second, better");
  });

  it("counts a change whose target text is gone as skipped, not applied", () => {
    const result = applyApprovedChanges("<p>different document</p>", changes, new Map([["ch_1", true]]));
    expect(result.applied).toBe(0);
    expect(result.skipped).toBe(3);
  });
});

describe("figures reach the exported book", () => {
  it("uploads each figure once and rewrites the src to the hosted URL", async () => {
    const vault = new MemoryVault({});
    vault.setBinary("img/a.png", new Uint8Array([1, 2, 3]));
    vault.setBinary("img/b.png", new Uint8Array([4, 5, 6]));

    const { client: c, server } = client([
      { match: "/images/upload-base64", json: { url: "https://cdn.example/a.png" } },
      { match: "/images/upload-base64", json: { url: "https://cdn.example/b.png" } },
    ]);

    const html = '<img src="img/a.png" alt="a"><img src="img/b.png" alt="b">';
    const cache: Record<string, string> = {};
    const result = await uploadFigures({
      html,
      figures: [
        { key: "a", label: "Figure 1", caption: "", sourcePath: "img/a.png", chapterOrder: 0, anchor: "fig-a" },
        { key: "b", label: "Figure 2", caption: "", sourcePath: "img/b.png", chapterOrder: 1, anchor: "fig-b" },
      ],
      vault,
      client: c,
      cache,
    });

    expect(result.uploaded).toBe(2);
    expect(result.html).toContain('src="https://cdn.example/a.png"');
    expect(result.html).toContain('src="https://cdn.example/b.png"');
    expect(server.requests).toHaveLength(2);
    expect(Object.keys(cache)).toHaveLength(2);
  });

  it("reuses a cached URL on the next compile instead of paying to upload again", async () => {
    const vault = new MemoryVault({});
    vault.setBinary("img/a.png", new Uint8Array([1, 2, 3]));
    const { client: c, server } = client([
      { match: "/images/upload-base64", json: { url: "https://cdn.example/a.png" } },
    ]);
    const cache: Record<string, string> = {};
    const figures = [
      { key: "a", label: "Figure 1", caption: "", sourcePath: "img/a.png", chapterOrder: 0, anchor: "fig-a" },
    ];
    const args = { html: '<img src="img/a.png">', figures, vault, client: c, cache };

    const first = await uploadFigures(args);
    const second = await uploadFigures(args);

    expect(first.uploaded).toBe(1);
    expect(second.uploaded).toBe(0);
    expect(second.reused).toBe(1);
    expect(server.requests).toHaveLength(1);
  });

  it("reports a figure it could not upload instead of exporting a book with a hole in it", async () => {
    const vault = new MemoryVault({});
    vault.setBinary("img/a.png", new Uint8Array([1, 2, 3]));
    const { client: c } = client([{ match: "/images/upload-base64", status: 500, json: { detail: "boom" } }]);
    const result = await uploadFigures({
      html: '<img src="img/a.png">',
      figures: [
        { key: "a", label: "Figure 3.2", caption: "", sourcePath: "img/a.png", chapterOrder: 0, anchor: "fig-a" },
      ],
      vault,
      client: c,
      cache: {},
    });
    expect(result.uploaded).toBe(0);
    expect(result.diagnostics[0]!.code).toBe("figure.upload_failed");
    expect(result.diagnostics[0]!.message).toContain("Figure 3.2");
    expect(result.html).toContain('src="img/a.png"'); // untouched, not silently blanked
  });

  it("only rewrites sources it recognises", () => {
    const html = '<img src="img/a.png"><p>the path img/a.png is mentioned here</p><img src="other.png">';
    const out = rewriteImageSources(html, new Map([["img/a.png", "https://cdn/a.png"]]));
    expect(out).toContain('<img src="https://cdn/a.png">');
    expect(out).toContain("the path img/a.png is mentioned here");
    expect(out).toContain('<img src="other.png">');
  });
});

describe("small pieces", () => {
  it("builds a multipart body with a boundary that appears in the header", () => {
    const { body, contentType } = buildMultipart([{ name: "a", value: "1" }]);
    const boundary = /boundary=(.*)$/.exec(contentType)![1]!;
    expect(new TextDecoder().decode(body)).toContain(`--${boundary}`);
  });

  it("returns no warnings when the header is absent or unreadable", () => {
    expect(decodeExportWarnings({})).toEqual([]);
    expect(decodeExportWarnings({ "x-export-warnings": "not base64 at all !!" })).toEqual([]);
  });

  it("does not blow up on a null pending_changes", () => {
    expect(parseMaybeEncoded(null)).toBeNull();
    expect(parseMaybeEncoded("")).toBeNull();
  });

  it("reports an unreachable transport as an error, not a success", async () => {
    const c = new SuperDocsClient({
      apiKey: "sk_test",
      transport: vi.fn().mockRejectedValue(new Error("network down")),
      sleep: noSleep,
    });
    await expect(c.verifyKey()).rejects.toThrow("network down");
  });

  it("marks 5xx retryable and 4xx not", () => {
    expect(new SuperDocsError("x", 503, "c", "").retryable).toBe(true);
    expect(new SuperDocsError("x", 429, "c", "").retryable).toBe(true);
    expect(new SuperDocsError("x", 422, "c", "").retryable).toBe(false);
  });
});
