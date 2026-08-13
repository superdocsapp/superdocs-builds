import { describe, expect, it } from "vitest";
import {
  normalizePollingPayload,
  normalizeSsePayload,
} from "../src/normalizers";

describe("response normalization", () => {
  it("unwraps polling transports and encoded pending changes", () => {
    const pending = JSON.stringify([
      {
        change_id: "c1",
        operation: "edit",
        chunk_id: "p-1",
        old_html: "<p>Old</p>",
        new_html: "<p>New</p>",
        ai_explanation: "Clearer",
      },
    ]);
    const payload = {
      data: JSON.stringify({
        job_id: "job-1",
        session_id: "session-1",
        status: "awaiting_approval",
        progress: 65,
        metadata: { pending_changes: pending },
      }),
    };

    expect(normalizePollingPayload(payload)).toMatchObject({
      jobId: "job-1",
      sessionId: "session-1",
      status: "awaiting_approval",
      progress: 65,
      changes: [
        {
          id: "c1",
          oldHtml: "<p>Old</p>",
          newHtml: "<p>New</p>",
        },
      ],
    });
  });

  it("parses SSE framing separately from double-encoded event data", () => {
    const encoded = JSON.stringify(
      JSON.stringify({ type: "proposed_change_batch", changes: [{ id: "c1" }] }),
    );
    const events = normalizeSsePayload(
      `event: proposed_change_batch\ndata: ${encoded}\n\n` +
        `event: usage\ndata: {"monthly_remaining":12}\n\n`,
    );

    expect(events).toEqual([
      { type: "proposed_change_batch", changes: [{ id: "c1" }] },
      { monthly_remaining: 12 },
    ]);
  });

  it("normalizes completed usage and updated HTML", () => {
    const job = normalizePollingPayload({
      status: "completed",
      result: {
        usage: { monthly_used: 4, monthly_remaining: 6, ops_charged: 1 },
        document_changes: { updated_html: "<p>Done</p>" },
      },
    });
    expect(job.usage).toEqual({
      monthlyUsed: 4,
      monthlyLimit: undefined,
      monthlyRemaining: 6,
      operationsCharged: 1,
      wasBillable: undefined,
    });
    expect(job.updatedHtml).toBe("<p>Done</p>");
  });

  it("normalizes continue prompts and rejects unknown operation names", () => {
    const job = normalizePollingPayload({
      status: "awaiting_approval",
      metadata: {
        awaiting_kind: "continue_prompt",
        pending_changes: [
          {
            change_id: "malicious",
            operation: `<img src=x onerror=alert(1)>`,
            insert_after_chunk_id: "chunk-1",
          },
        ],
      },
    });

    expect(job.awaitingKind).toBe("continue_prompt");
    expect(job.changes[0]).toMatchObject({
      id: "malicious",
      operation: "unknown",
      insertAfterChunkId: "chunk-1",
    });
  });
});
