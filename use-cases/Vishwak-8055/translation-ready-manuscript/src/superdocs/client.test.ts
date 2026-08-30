import { describe, expect, it, vi } from "vitest";
import {
  SuperDocsAuthError,
  SuperDocsClient,
  SuperDocsRateLimitError,
  SuperDocsTimeoutError,
  SuperDocsValidationError,
  buildApprovePayload,
  parseProposedChangeBatchEvent,
} from "./client.js";

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

describe("parseProposedChangeBatchEvent — the documented double-JSON-parse gotcha", () => {
  it("parses the exact shape documented at docs.superdocs.app/guides/human-in-the-loop: outer.content is itself JSON-encoded", () => {
    const innerBatch = { type: "proposed_change_batch", batch_id: "batch_123", batch_total: 2, changes: [{ change_id: "c1", chunk_id: "chunk-title" }, { change_id: "c2", chunk_id: "chunk-p1" }] };
    // This is what actually arrives as event.data: an object whose .content is a JSON STRING, not the object itself.
    const rawEventData = JSON.stringify({ content: JSON.stringify(innerBatch) });

    const parsed = parseProposedChangeBatchEvent(rawEventData);
    expect(parsed.batchId).toBe("batch_123");
    expect(parsed.batchTotal).toBe(2);
    expect(parsed.changes).toHaveLength(2);
    expect(parsed.changes[0]?.changeId).toBe("c1");
  });

  it("throws a clear error if outer.content is not a string (i.e. someone already parsed it, or the API changed shape) rather than silently returning garbage", () => {
    const rawEventData = JSON.stringify({ content: { already: "an object, not a string" } });
    expect(() => parseProposedChangeBatchEvent(rawEventData)).toThrow(/expected outer.content to be a JSON-encoded string/);
  });

  it("throws (does not silently swallow) if the outer payload itself is not valid JSON", () => {
    expect(() => parseProposedChangeBatchEvent("not json at all")).toThrow();
  });
});

describe("buildApprovePayload — the documented required-top-level-approved gotcha", () => {
  it("always includes a top-level approved:true alongside per-change decisions", () => {
    const payload = buildApprovePayload([
      { changeId: "c1", approved: true },
      { changeId: "c2", approved: false, feedback: "term should stay untranslated" },
    ]);
    expect(payload.approved).toBe(true);
    expect(payload.changes).toEqual([
      { change_id: "c1", approved: true },
      { change_id: "c2", approved: false, feedback: "term should stay untranslated" },
    ]);
  });

  it("still sets top-level approved:true even when every individual decision is a rejection -- it gates the request being processed, not the outcome", () => {
    const payload = buildApprovePayload([{ changeId: "c1", approved: false }]);
    expect(payload.approved).toBe(true);
    expect(payload.changes[0]?.approved).toBe(false);
  });
});

describe("SuperDocsClient", () => {
  it("throws a clear error rather than making a request when no API key is configured", async () => {
    const client = new SuperDocsClient({ apiKey: undefined, fetchImpl: vi.fn() as unknown as typeof fetch });
    await expect(client.getJob("job1")).rejects.toThrow(/no API key/);
  });

  it("sends Bearer auth on every request", async () => {
    const fetchSpy = vi.fn(async (_url: string, _init: RequestInit) => jsonResponse({ job_id: "job1", status: "completed" }));
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
    await client.getJob("job1");
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer sk_test");
  });

  it("renameDocument PATCHes /v1/documents/{id} with just the title field", async () => {
    const fetchSpy = vi.fn(async (_url: string, _init: RequestInit) => jsonResponse({ status: "renamed" }));
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
    const result = await client.renameDocument("doc_abc", "New Title");
    expect(result.status).toBe("renamed");
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.superdocs.app/v1/documents/doc_abc");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ title: "New Title" });
  });

  it("chat() unwraps data.document_changes.updated_html and data.usage from the documented response envelope", async () => {
    const fetchSpy = vi.fn(async () =>
      jsonResponse({ data: { document_changes: { updated_html: "<p>hi</p>" }, usage: { monthly_used: 5, monthly_limit: 100, quota_exhausted: false } } }),
    );
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
    const result = await client.chat({ message: "translate this", sessionId: "s1" });
    expect(result.updatedHtml).toBe("<p>hi</p>");
    expect(result.usage).toEqual({ monthlyUsed: 5, monthlyLimit: 100, quotaExhausted: false });
  });

  it("pollJobUntilSettled polls until status leaves pending/in_progress, not on the first response", async () => {
    let call = 0;
    const fetchSpy = vi.fn(async () => {
      call++;
      if (call < 3) return jsonResponse({ job_id: "job1", status: "in_progress" });
      return jsonResponse({ job_id: "job1", status: "completed", metadata: { pending_changes: [] } });
    });
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
    const result = await client.pollJobUntilSettled("job1", { intervalMs: 1 });
    expect(call).toBe(3);
    expect(result.status).toBe("completed");
  });

  it("pollJobUntilSettled treats awaiting_approval as settled (stops polling), since that's a real state requiring human action, not a transient one", async () => {
    const fetchSpy = vi.fn(async () => jsonResponse({ job_id: "job1", status: "awaiting_approval", metadata: { pending_changes: [{ change_id: "c1", chunk_id: "chunk-title" }] } }));
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
    const result = await client.pollJobUntilSettled("job1", { intervalMs: 1 });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(result.status).toBe("awaiting_approval");
    expect(result.pendingChanges).toHaveLength(1);
  });

  it("approveChanges sends the buildApprovePayload shape to /v1/chat/{sessionId}/approve", async () => {
    const fetchSpy = vi.fn(async (_url: string, _init: RequestInit) => jsonResponse({ status: "approved" }));
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
    await client.approveChanges("session1", [{ changeId: "c1", approved: true }]);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.superdocs.app/v1/chat/session1/approve");
    const body = JSON.parse(init.body as string);
    expect(body.approved).toBe(true);
    expect(body.changes).toEqual([{ change_id: "c1", approved: true }]);
  });

  it("uploadDocument posts multipart form data with the file and returns the parsed upload result", async () => {
    const fetchSpy = vi.fn(async (_url: string, _init: RequestInit) => jsonResponse({ html: "<p>x</p>", session_id: "s1", filename: "alice.txt", chunks_count: 3, version_id: "v1" }));
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
    const result = await client.uploadDocument(new Blob(["hello"]), "alice.txt");
    expect(result).toEqual({ html: "<p>x</p>", sessionId: "s1", filename: "alice.txt", chunksCount: 3, versionId: "v1" });
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("exportDocument returns the raw response blob for the requested format", async () => {
    const fetchSpy = vi.fn(async () => new Response(new Blob(["docx-bytes"]), { status: 200 }));
    const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
    const blob = await client.exportDocument({ sessionId: "s1", format: "docx" });
    expect(await blob.text()).toBe("docx-bytes");
  });

  describe("error status mapping", () => {
    it("maps 401 to SuperDocsAuthError", async () => {
      const fetchSpy = vi.fn(async () => new Response("unauthorized", { status: 401, statusText: "Unauthorized" }));
      const client = new SuperDocsClient({ apiKey: "bad-key", fetchImpl: fetchSpy as unknown as typeof fetch });
      await expect(client.getJob("job1")).rejects.toBeInstanceOf(SuperDocsAuthError);
    });

    it("maps 429 to SuperDocsRateLimitError and surfaces Retry-After", async () => {
      const fetchSpy = vi.fn(async () => new Response("rate limited", { status: 429, statusText: "Too Many Requests", headers: { "retry-after": "30" } }));
      const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
      try {
        await client.getJob("job1");
        expect.unreachable("should have thrown");
      } catch (err) {
        expect(err).toBeInstanceOf(SuperDocsRateLimitError);
        expect((err as InstanceType<typeof SuperDocsRateLimitError>).retryAfterSeconds).toBe(30);
      }
    });

    it("maps 422 to SuperDocsValidationError", async () => {
      const fetchSpy = vi.fn(async () => new Response("missing approved field", { status: 422, statusText: "Unprocessable Entity" }));
      const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
      await expect(client.approveChanges("s1", [])).rejects.toBeInstanceOf(SuperDocsValidationError);
    });

    it("maps 504 to SuperDocsTimeoutError, distinct from a hard failure -- large documents can legitimately take minutes", async () => {
      const fetchSpy = vi.fn(async () => new Response("gateway timeout", { status: 504, statusText: "Gateway Timeout" }));
      const client = new SuperDocsClient({ apiKey: "sk_test", fetchImpl: fetchSpy as unknown as typeof fetch });
      await expect(client.getJob("job1")).rejects.toBeInstanceOf(SuperDocsTimeoutError);
    });
  });
});
