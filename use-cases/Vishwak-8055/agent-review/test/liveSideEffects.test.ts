import { describe, expect, it, vi } from "vitest";
import { LiveSuperDocsSideEffects } from "../src/liveSideEffects";
import { SuperDocsClient } from "../src/superdocsClient";

function fakeClient(handlers: Record<string, (init: RequestInit) => unknown>) {
  const fetchImpl = vi.fn(async (url: string, init: RequestInit) => {
    const parsed = new URL(url);
    const path = parsed.pathname + parsed.search;
    const matchedKey = Object.keys(handlers).find((k) => path.startsWith(k));
    if (!matchedKey) throw new Error(`Unhandled fake request: ${init.method ?? "GET"} ${path}`);
    return new Response(JSON.stringify(handlers[matchedKey]!(init)), { status: 200 });
  }) as unknown as typeof fetch;
  return new SuperDocsClient({ apiKey: "sk_test", fetchImpl });
}

describe("LiveSuperDocsSideEffects.applyPatch", () => {
  it("computes the target HTML client-side and sends it verbatim via editDocument", async () => {
    let editRequestBody: unknown;
    const client = fakeClient({
      "/v1/sessions/s1/history": () => ({
        messages: [],
        document_state: { html: '<p data-chunk-id="a">current</p><p data-chunk-id="b">keep</p>' },
      }),
      "/v1/chat/async": (init) => {
        editRequestBody = JSON.parse(init.body as string);
        return { job_id: "job_new", session_id: "s1" };
      },
    });
    const sideEffects = new LiveSuperDocsSideEffects(client);

    await sideEffects.applyPatch({
      sessionId: "s1",
      documentId: "doc1",
      patch: { kind: "restore", chunkId: "a", html: '<p data-chunk-id="a">restored</p>' },
    });

    expect(editRequestBody).toMatchObject({
      session_id: "s1",
      document_html: '<p data-chunk-id="a">restored</p><p data-chunk-id="b">keep</p>',
      approval_mode: "approve_all",
    });
  });

  it("throws rather than silently no-op-ing when the session has no document state", async () => {
    const client = fakeClient({
      "/v1/sessions/s1/history": () => ({ messages: [], document_state: null }),
    });
    const sideEffects = new LiveSuperDocsSideEffects(client);
    await expect(
      sideEffects.applyPatch({ sessionId: "s1", documentId: "doc1", patch: { kind: "remove", chunkId: "a" } })
    ).rejects.toThrow(/no current document state/);
  });
});

describe("LiveSuperDocsSideEffects.decideHitlChange", () => {
  it("forwards to SuperDocs's approve endpoint with the right shape", async () => {
    let body: unknown;
    const client = fakeClient({
      "/v1/chat/s1/approve": (init) => {
        body = JSON.parse(init.body as string);
        return { job_id: "job_1", status: "completed" };
      },
    });
    const sideEffects = new LiveSuperDocsSideEffects(client);
    await sideEffects.decideHitlChange({
      sessionId: "s1",
      jobId: "job_1",
      changeId: "ch_1",
      approved: false,
      feedback: "not needed",
    });
    expect(body).toEqual({ job_id: "job_1", change_id: "ch_1", approved: false, feedback: "not needed" });
  });
});
