import { describe, expect, it, vi } from "vitest";
import { SuperDocsIntegration, emptySuperDocsState } from "./integration.js";
import type { SuperDocsClient } from "./client.js";

function fakeClient(): SuperDocsClient {
  return {
    uploadDocument: vi.fn(async () => { throw new Error("SuperDocs API 404 Not Found"); }),
    chatAsync: vi.fn(async () => ({ jobId: "job-1" })),
    pollJobUntilSettled: vi.fn(async () => ({ jobId: "job-1", status: "awaiting_approval", pendingChanges: [{ changeId: "c1", chunkId: "chunk-1" }], updatedHtml: null, raw: {} })),
    getJob: vi.fn(async () => ({ jobId: "job-1", status: "completed", pendingChanges: [], updatedHtml: "<p data-chunk-id=\"chunk-1\">done</p>", raw: {} })),
    approveChanges: vi.fn(async () => ({ status: "approved" })),
    exportDocument: vi.fn(async () => new Blob(["docx"])),
    probeAuth: vi.fn(async () => ({ authenticated: true, status: 404 })),
  } as unknown as SuperDocsClient;
}

describe("SuperDocsIntegration", () => {
  it("falls back from a legacy upload 404 to the current HTML-first async workflow", async () => {
    const client = fakeClient();
    const integration = new SuperDocsIntegration(client);
    const state = await integration.prepareDocument(emptySuperDocsState(), "<p data-chunk-id=\"chunk-1\">source</p>", "source.html", "Prepare for translation.");
    expect(state.status).toBe("awaiting_approval");
    expect(state.pendingChanges).toHaveLength(1);
    expect(client.chatAsync).toHaveBeenCalled();
  });

  it("keeps approval explicit and returns the refreshed state", async () => {
    const client = fakeClient();
    const integration = new SuperDocsIntegration(client);
    const state = { ...emptySuperDocsState(), status: "awaiting_approval" as const, sessionId: "s1", jobId: "job-1", pendingChanges: [{ changeId: "c1", chunkId: "chunk-1" }] };
    const approved = await integration.approve(state, [{ changeId: "c1", approved: true }]);
    expect(approved.status).toBe("completed");
    expect(client.approveChanges).toHaveBeenCalledWith("s1", [{ changeId: "c1", approved: true }]);
  });
});
