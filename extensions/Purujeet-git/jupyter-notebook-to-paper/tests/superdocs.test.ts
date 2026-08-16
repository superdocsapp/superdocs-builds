import { afterEach, describe, expect, it, vi } from "vitest";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { SuperDocsClient } from "../src/superdocs.js";
import { readUsageLedger, summarizeUsage } from "../src/telemetry.js";

describe("SuperDocsClient", () => {
  afterEach(() => vi.restoreAllMocks());

  it("supports chat, itemized approval, and binary export", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({
        session_id: "session-1",
        document_changes: { updated_html: "<p>Updated</p>" },
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ approved: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(new Uint8Array([1, 2, 3]), { status: 200 }));
    const client = new SuperDocsClient({
      apiKey: "sk_test",
      baseUrl: "https://example.test/",
    });

    const chat = await client.chat({
      message: "Improve the results section",
      session_id: "session-1",
      document_html: "<p>Results</p>",
      approval_mode: "ask_every_time",
    });
    await client.approve("session-1", {
      jobId: "job-1",
      approved: true,
      changes: [{ changeId: "change-1", approved: false, feedback: "Keep this unchanged" }],
    });
    const exported = await client.exportDocument({
      html: "<p>Results</p>",
      format: "docx",
      filename: "results.docx",
    });

    expect(chat.sessionId).toBe("session-1");
    expect(exported).toEqual(Buffer.from([1, 2, 3]));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1]?.[0]).toContain("/v1/chat/session-1/approve");
    expect(fetchMock.mock.calls[2]?.[0]).toContain("/v1/documents/export");
  });

  it("returns a job id and polls an async job", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({
        job_id: "job-async-1",
        session_id: "session-async-1",
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        status: "completed",
        document_changes: { pending_changes: [{ change_id: "change-1" }] },
      }), { status: 200 }));
    const client = new SuperDocsClient({ apiKey: "sk_test", baseUrl: "https://example.test" });

    const submitted = await client.chatAsync({
      message: "Rewrite the first paragraph",
      session_id: "session-async-1",
      document_html: "<p>Results</p>",
      approval_mode: "ask_every_time",
    });
    const job = await client.waitForJob(submitted.jobId, { pollIntervalMs: 0, maxWaitMs: 1000 });

    expect(submitted.jobId).toBe("job-async-1");
    expect(submitted.sessionId).toBe("session-async-1");
    expect(job.status).toBe("completed");
    expect(fetchMock.mock.calls[1]?.[0]).toContain("/v1/jobs/job-async-1");
  });

  it("rejects empty documents before making a request", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const client = new SuperDocsClient({ apiKey: "sk_test", baseUrl: "https://example.test" });

    await expect(client.chat({ message: "Edit", session_id: "session-1", document_html: "" })).rejects.toThrow("non-empty");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("persists provider-reported usage telemetry", async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "superdocs-usage-"));
    const usagePath = path.join(directory, "usage.json");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({
      session_id: "usage-session",
      document_changes: { updated_html: "<p>Updated</p>" },
      usage: {
        monthly_used: 51,
        monthly_limit: 500,
        monthly_remaining: 449,
        was_billable: true,
        ops_charged: 1,
        subscription_tier: "free",
      },
    }), { status: 200 }));
    const client = new SuperDocsClient({ apiKey: "sk_test", baseUrl: "https://example.test", usagePath });

    await client.chat({ message: "Edit", session_id: "usage-session", document_html: "<p>Results</p>" });
    const ledger = await readUsageLedger(usagePath);

    expect(ledger.records).toHaveLength(1);
    expect(ledger.records[0]).toMatchObject({ operation: "chat", wasBillable: true, operationsCharged: 1 });
    expect(summarizeUsage(ledger)).toMatchObject({ recordCount: 1, billableRecords: 1, operationsCharged: 1 });
  });
});
