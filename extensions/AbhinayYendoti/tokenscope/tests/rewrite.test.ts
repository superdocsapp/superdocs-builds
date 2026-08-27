import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadConfig } from "../server/config.js";
import { TokenScopeError } from "../server/errors.js";
import { applyChange, measureWholeDocument, rewriteSelection } from "../server/rewrite.js";
import { resolveSelection } from "../shared/selection.js";
import { countTextTokens } from "../shared/tokens.js";
import type { DocumentSnapshot } from "../shared/types.js";

/**
 * The rewrite orchestration, against a stubbed SuperDocs.
 *
 * `fetch` is what is faked, not the client: the real request is built, the real
 * response is parsed by the real zod schemas, and the real error mapping runs.
 * The fixture bodies below are the shapes the live API returned during
 * development, trimmed to the fields TokenScope reads.
 */

const DOCUMENT: DocumentSnapshot = {
  paragraphs: [
    { id: "p0", text: "Quarterly Review" },
    { id: "p1", text: "The quarterly review covers three business units." },
    {
      id: "p2",
      text:
        "Notwithstanding the foregoing, it should be noted that the parties hereto have " +
        "undertaken a not insubstantial number of initiatives."
    },
    { id: "p3", text: "Headcount grew by eleven people, concentrated in engineering." }
  ]
};

const SELECTION = resolveSelection(DOCUMENT, DOCUMENT.paragraphs[2]!.text);
const INSTRUCTION = "Make this more concise.";

interface Call {
  url: string;
  method: string;
  body: Record<string, unknown> | undefined;
}

let calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function jobBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    job_id: "job-1",
    session_id: "session-1",
    status: "awaiting_approval",
    progress: 88,
    metadata: {
      cumulative_tokens: 87_303,
      pending_changes: [
        {
          change_id: "change-1",
          chunk_id: "chunk-1",
          operation: "edit",
          old_html: `<p data-chunk-id="chunk-1">${DOCUMENT.paragraphs[2]!.text}</p>`,
          new_html: '<p data-chunk-id="chunk-1">The parties undertook significant initiatives.</p>',
          ai_explanation: "Proposed: rewrite this paragraph to be more concise."
        }
      ]
    },
    ...overrides
  };
}

/** Route the stub by path. Every handler returns a Response. */
function stub(routes: {
  chatAsync?: () => Response;
  job?: () => Response;
  approve?: () => Response;
}) {
  const fetchStub = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const raw = init?.body;

    calls.push({
      url,
      method,
      body: typeof raw === "string" ? (JSON.parse(raw) as Record<string, unknown>) : undefined
    });

    if (url.includes("/chat/async")) return (routes.chatAsync ?? defaultChatAsync)();
    if (url.includes("/approve")) return (routes.approve ?? (() => json(200, { ok: true })))();
    if (url.includes("/jobs/")) return (routes.job ?? (() => json(200, jobBody())))();

    throw new Error(`unstubbed call: ${method} ${url}`);
  });

  vi.stubGlobal("fetch", fetchStub);
}

const defaultChatAsync = () =>
  json(200, { job_id: "job-1", session_id: "session-1", status: "pending" });

function chatCall(): Call {
  const call = calls.find((c) => c.url.includes("/chat/async"));
  if (call === undefined) throw new Error("no /chat/async call was made");
  return call;
}

beforeEach(() => {
  calls = [];
  loadConfig({ SUPERDOCS_API_KEY: "sk_test_key", SUPERDOCS_MODEL_TIER: "core" });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("rewriteSelection", () => {
  it("sends the selected text and the instruction to SuperDocs", async () => {
    stub({});
    await rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION });

    const message = chatCall().body?.["message"] as string;

    expect(message).toContain(DOCUMENT.paragraphs[2]!.text);
    expect(message).toContain(`Instruction: ${INSTRUCTION}`);
  });

  it("sends the whole document so SuperDocs can locate the selection in it", async () => {
    stub({});
    await rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION });

    const html = chatCall().body?.["document_html"] as string;

    for (const paragraph of DOCUMENT.paragraphs) expect(html).toContain(paragraph.text);
  });

  it("asks for approval on every change, so nothing is applied by the rewrite itself", async () => {
    stub({});
    await rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION });

    expect(chatCall().body?.["approval_mode"]).toBe("ask_every_time");
    expect(calls.some((c) => c.url.includes("/approve"))).toBe(false);
  });

  it("measures in a fresh session, so the cost is this operation's alone", async () => {
    stub({});
    const a = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    });

    calls = [];

    const b = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    });

    expect(a.sessionId).not.toBe(b.sessionId);
    expect(a.sessionId).toMatch(/^tokenscope-surgical-/u);
  });

  it("parses the proposed change back into old and new text", async () => {
    stub({});
    const result = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    });

    expect(result.changes).toHaveLength(1);
    expect(result.changes[0]!.changeId).toBe("change-1");
    expect(result.changes[0]!.oldText).toBe(DOCUMENT.paragraphs[2]!.text);
    expect(result.changes[0]!.newText).toBe("The parties undertook significant initiatives.");
    expect(result.changes[0]!.explanation).toContain("more concise");
  });

  it("reports the token cost SuperDocs measured, labelled as measured", async () => {
    stub({});
    const result = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    });

    expect(result.measurement.reported.surgical?.tokens).toBe(87_303);
    expect(result.measurement.reported.surgical?.source).toBe("measured");
  });

  it("counts the text the job actually wrote, from the change it returned", async () => {
    stub({});
    const result = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    });

    expect(result.work.sectionsChanged).toBe(1);
    expect(result.work.output.tokens).toBe(
      countTextTokens("The parties undertook significant initiatives.")
    );
    expect(result.measurement.written.surgical?.source).toBe("tokenized");
  });

  it("estimates the whole-document cost until one is measured, and labels it", async () => {
    stub({});
    const { measurement } = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    });

    expect(measurement.reported.wholeDocument?.source).toBe("estimated");
    expect(measurement.reported.wholeDocument!.tokens).toBeGreaterThan(
      measurement.reported.surgical!.tokens
    );
    expect(measurement.reported.savings?.tokens).toBe(
      measurement.reported.wholeDocument!.tokens - measurement.reported.surgical!.tokens
    );

    // A regeneration has to emit the whole document; a surgical edit, one paragraph.
    expect(measurement.written.wholeDocument?.source).toBe("estimated");
    expect(measurement.written.wholeDocument!.tokens).toBe(measurement.document.tokens);
    expect(measurement.written.savings!.ratio).toBeGreaterThan(0);
  });

  it("separates a change outside the selection from the one inside it", async () => {
    stub({
      job: () =>
        json(
          200,
          jobBody({
            metadata: {
              cumulative_tokens: 1000,
              pending_changes: [
                {
                  change_id: "in",
                  old_html: `<p>${DOCUMENT.paragraphs[2]!.text}</p>`,
                  new_html: "<p>Shorter.</p>"
                },
                {
                  change_id: "out",
                  old_html: `<p>${DOCUMENT.paragraphs[3]!.text}</p>`,
                  new_html: "<p>Headcount rose.</p>"
                }
              ]
            }
          })
        )
    });

    const result = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    });

    expect(result.scope.inScope.map((c) => c.changeId)).toEqual(["in"]);
    expect(result.scope.outOfScope.map((c) => c.changeId)).toEqual(["out"]);
  });

  it("reports no number rather than a made-up one when SuperDocs reports none", async () => {
    // The live 300-page run did exactly this: the job completed and carried no
    // cumulative_tokens at all.
    stub({
      job: () =>
        json(
          200,
          jobBody({
            status: "completed",
            metadata: {
              pending_changes: [
                {
                  change_id: "change-1",
                  old_html: `<p>${DOCUMENT.paragraphs[2]!.text}</p>`,
                  new_html: "<p>Shorter.</p>"
                }
              ]
            }
          })
        )
    });

    const { measurement, work } = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    });

    expect(measurement.reported.surgical).toBeNull();
    expect(measurement.reported.wholeDocument).toBeNull();
    expect(measurement.reported.savings).toBeNull();

    // The comparison that does not depend on the provider counter still works.
    expect(work.sectionsChanged).toBe(1);
    expect(measurement.written.surgical!.tokens).toBeGreaterThan(0);
    expect(measurement.written.savings!.ratio).toBeGreaterThan(0);
  });

  it("turns a rejected key into an actionable error, not a stack trace", async () => {
    stub({ chatAsync: () => json(401, { detail: "Invalid API key" }) });

    const error = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(TokenScopeError);
    expect((error as TokenScopeError).code).toBe("auth_failed");
    expect((error as TokenScopeError).hint).toContain("SUPERDOCS_API_KEY");
  });

  it("reports an exhausted quota as its own error", async () => {
    stub({ chatAsync: () => json(429, { detail: "quota" }) });

    await expect(
      rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION })
    ).rejects.toMatchObject({ code: "quota_exhausted" });
  });

  it("reports a failed job instead of returning an empty result", async () => {
    stub({ job: () => json(200, jobBody({ status: "failed", error: "model unavailable" })) });

    await expect(
      rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION })
    ).rejects.toMatchObject({ code: "job_failed" });
  });

  it("reports a body it does not recognise rather than reading fields off it", async () => {
    stub({ chatAsync: () => json(200, { unexpected: true }) });

    await expect(
      rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION })
    ).rejects.toMatchObject({ code: "unexpected_response" });
  });

  it("reports a non-JSON body without trying to parse it", async () => {
    stub({ chatAsync: () => new Response("<html>502 Bad Gateway</html>", { status: 200 }) });

    await expect(
      rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION })
    ).rejects.toMatchObject({ code: "unexpected_response" });
  });

  it("refuses to run at all without a key, before any network call", async () => {
    loadConfig({});
    stub({});

    await expect(
      rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION })
    ).rejects.toMatchObject({ code: "no_api_key" });

    expect(calls).toHaveLength(0);
  });
});

describe("measureWholeDocument", () => {
  it("asks for a full regeneration, in a session of its own", async () => {
    stub({ job: () => json(200, jobBody({ status: "completed", progress: 100 })) });

    const run = await measureWholeDocument({ document: DOCUMENT, instruction: INSTRUCTION });
    const message = chatCall().body?.["message"] as string;

    expect(message).toContain("Regenerate this document in full");
    expect(message).toContain(`Instruction: ${INSTRUCTION}`);
    expect(message).not.toContain("<<<SELECTION");
    expect(run.sessionId).toMatch(/^tokenscope-wholedoc-/u);
  });

  it("returns what SuperDocs reported, and what the job actually wrote", async () => {
    stub({
      job: () =>
        json(
          200,
          jobBody({
            status: "completed",
            metadata: {
              cumulative_tokens: 1_009_856,
              pending_changes: [
                { change_id: "a", old_html: "<p>one</p>", new_html: "<p>first section</p>" },
                { change_id: "b", old_html: "<p>two</p>", new_html: "<p>second section</p>" }
              ]
            }
          })
        )
    });

    const run = await measureWholeDocument({ document: DOCUMENT, instruction: INSTRUCTION });

    expect(run.reportedTokens).toBe(1_009_856);
    expect(run.work.sectionsChanged).toBe(2);
    expect(run.work.output.tokens).toBe(
      countTextTokens("first section") + countTextTokens("second section")
    );
  });

  it("reports null, not zero, when SuperDocs reports no cost for the regeneration", async () => {
    stub({ job: () => json(200, jobBody({ status: "completed", metadata: {} })) });

    const run = await measureWholeDocument({ document: DOCUMENT, instruction: INSTRUCTION });

    expect(run.reportedTokens).toBeNull();
  });

  it("never approves anything it proposed", async () => {
    stub({ job: () => json(200, jobBody({ status: "completed" })) });
    await measureWholeDocument({ document: DOCUMENT, instruction: INSTRUCTION });

    expect(calls.some((c) => c.url.includes("/approve"))).toBe(false);
  });
});

describe("applyChange", () => {
  it("approves exactly the change it was given, naming the job", async () => {
    stub({});
    await applyChange({ sessionId: "session-1", jobId: "job-1", changeId: "change-1" });

    const approve = calls.find((c) => c.url.includes("/approve"));

    expect(approve?.method).toBe("POST");
    expect(approve?.url).toContain("/chat/session-1/approve");
    expect(approve?.body).toEqual({ job_id: "job-1", change_id: "change-1", approved: true });
  });
});

describe("transient upstream faults", () => {
  it("retries a 503 while polling instead of losing the run", async () => {
    // A 300-page benchmark run was lost at 99% to exactly this.
    let polls = 0;

    stub({
      job: () => {
        polls += 1;
        return polls === 1 ? json(503, { detail: "upstream unavailable" }) : json(200, jobBody());
      }
    });

    const result = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    });

    // 503, then the compact poll that sees it settled, then the one full read.
    expect(polls).toBe(3);
    expect(result.measurement.reported.surgical?.tokens).toBe(87_303);
  });

  it("gives up, with a useful error, once the retries are exhausted", async () => {
    stub({ job: () => json(503, { detail: "upstream unavailable" }) });

    await expect(
      rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION })
    ).rejects.toMatchObject({ code: "upstream_error" });
  });

  it("does not retry a rejected key", async () => {
    let attempts = 0;

    stub({
      chatAsync: () => {
        attempts += 1;
        return json(401, { detail: "Invalid API key" });
      }
    });

    await expect(
      rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION })
    ).rejects.toMatchObject({ code: "auth_failed" });

    expect(attempts).toBe(1);
  });

  it("reuses one idempotency key across retries, so a retry cannot bill twice", async () => {
    let attempts = 0;

    stub({
      chatAsync: () => {
        attempts += 1;
        return attempts === 1 ? json(503, { detail: "gateway" }) : defaultChatAsync();
      }
    });

    await rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION });

    const keys = new Set(
      (globalThis.fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls
        .filter(([url]) => url.includes("/chat/async"))
        .map(([, init]) => (init.headers as Record<string, string>)["Idempotency-Key"])
    );

    expect(attempts).toBe(2);
    expect(keys.size).toBe(1);
  });
});

describe("polling large jobs", () => {
  it("polls compact and reads the full record only once it has settled", async () => {
    let polls = 0;

    stub({
      job: () => {
        polls += 1;
        // Still running on the first poll, settled on the second.
        return polls === 1
          ? json(200, jobBody({ status: "in_progress", progress: 40 }))
          : json(200, jobBody());
      }
    });

    await rewriteSelection({ document: DOCUMENT, selection: SELECTION, instruction: INSTRUCTION });

    const jobCalls = calls.filter((c) => c.url.includes("/jobs/"));
    const compact = jobCalls.filter((c) => c.url.includes("compact=true"));
    const full = jobCalls.filter((c) => !c.url.includes("compact=true"));

    expect(compact.length).toBe(2);
    expect(full.length).toBe(1);
  });

  it("maps a timeout while reading a huge job body to a timeout error", async () => {
    // AbortSignal.timeout rejects response.text(), not fetch, when the body is
    // still streaming. That rejection used to escape as a raw DOMException.
    stub({
      job: () =>
        new Response(
          new ReadableStream({
            start(controller) {
              controller.enqueue(new TextEncoder().encode('{"job_id":"job-1"'));
              controller.error(
                Object.assign(new Error("The operation was aborted due to timeout"), {
                  name: "TimeoutError"
                })
              );
            }
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
    });

    const error = await rewriteSelection({
      document: DOCUMENT,
      selection: SELECTION,
      instruction: INSTRUCTION
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(TokenScopeError);
    expect((error as TokenScopeError).code).toBe("timeout");
  });
});
