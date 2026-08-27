import { describe, expect, it } from "vitest";
import {
  describeFailure,
  normalizePollingPayload,
  normalizeSelectedHtml,
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

  it("accepts documented and live Sigma selection response shapes", () => {
    expect(normalizeSelectedHtml("<p>Selected</p>")).toBe("<p>Selected</p>");
    expect(
      normalizeSelectedHtml({
        response: [{ isSuccess: true, response: "<p>Selected</p>" }],
        widgetID: "writer",
        sourceWidgetID: "extension",
      }),
    ).toBe("<p>Selected</p>");
    expect(
      normalizeSelectedHtml({ data: "<p>Selected</p>", message: "success" }),
    ).toBe("<p>Selected</p>");
    expect(
      normalizeSelectedHtml({
        data: { content: "<p>Selected</p>" },
        message: "success",
      }),
    ).toBe("<p>Selected</p>");
    expect(
      normalizeSelectedHtml({
        data: { content: { html: "<p>Selected</p>", text: "Selected" } },
        message: "Data fetched from writer",
      }),
    ).toBe("<p>Selected</p>");
    expect(
      normalizeSelectedHtml({
        data: { content: { data: { content: "<p>Selected</p>" } } },
        message: "Data fetched from writer",
      }),
    ).toBe("<p>Selected</p>");
    expect(normalizeSelectedHtml({ data: "", message: "success" })).toBe("");
  });

  it("reports detail from non-Error Sigma rejections", () => {
    expect(describeFailure(new Error("Boom"))).toBe("Boom");
    expect(
      describeFailure({ message: "Connection not authorised", status: 401 }),
    ).toBe(
      "Connection not authorised (status 401) [object(message:string,status:number)]",
    );
    expect(describeFailure({ error: { message: "Invalid API key" } })).toBe(
      "Invalid API key [object(error:object(message:string))]",
    );
    expect(describeFailure({ unknownField: 12 })).toBe(
      "Request failed: object(unknownField:number)",
    );
    expect(describeFailure(undefined)).toBe("An unexpected error occurred.");
  });

  it("follows only allowlisted selection keys", () => {
    const unrelated = "<p>Some other string in the envelope</p>";
    expect(() =>
      normalizeSelectedHtml({ data: { payload: unrelated }, message: "ok" }),
    ).toThrow("Writer returned an unexpected selection response");
  });

  it("reports the failing shape and Writer status without leaking content", () => {
    const secret = "CONFIDENTIAL DOCUMENT CONTENT";
    try {
      normalizeSelectedHtml({
        data: { unexpected: secret },
        message: "selection unavailable",
      });
      throw new Error("Expected normalizeSelectedHtml to throw.");
    } catch (error) {
      const text = String(error);
      expect(text).toContain("data:object(unexpected:string)");
      expect(text).toContain("Writer said: selection unavailable");
      expect(text).not.toContain(secret);
    }
  });
});
