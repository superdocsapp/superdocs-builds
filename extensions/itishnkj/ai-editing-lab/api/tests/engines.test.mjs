import assert from "node:assert/strict";
import test from "node:test";

import {
  parseDiyModelOutput,
  parseWithOneRepair,
} from "../src/lib/engines/diy/parser.ts";
import {
  buildDiyMessages,
  DIY_PROMPT_VERSION,
} from "../src/lib/engines/diy/prompt.ts";
import {
  aggregateDiyRequestMetrics,
  aggregateDiyUsage,
} from "../src/lib/engines/diy/diyEngine.ts";
import { validateDocumentHtml } from "../src/lib/engines/validation.ts";
import {
  SuperdocsEngine,
  getSuperdocsPublicConfig,
} from "../src/lib/engines/superdocs/superdocsEngine.ts";

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function superdocsRequest() {
  return {
    documentHtml: '<p data-chunk-id="intro">Original.</p>',
    selectionHtml: null,
    selectionText: null,
    selectionFrom: null,
    selectionTo: null,
    scope: "document",
    instruction: "Make this clearer.",
    preset: null,
    requestId: "request-1",
    currentVersionId: "version-1",
  };
}

test("validates the structured DIY response", () => {
  assert.deepEqual(
    parseDiyModelOutput(
      JSON.stringify({
        replacement_html: "<p>Clearer copy.</p>",
        explanation: "Improved clarity.",
      }),
    ),
    {
      replacement_html: "<p>Clearer copy.</p>",
      explanation: "Improved clarity.",
    },
  );
});

test("rejects malformed or incomplete DIY output", () => {
  assert.throws(() => parseDiyModelOutput("not json"), /malformed JSON/);
  assert.throws(
    () => parseDiyModelOutput(JSON.stringify({ explanation: "Missing edit" })),
    /replacement_html/,
  );
});

test("labels and assembles the bounded DIY selection prompt contract", () => {
  const selectionHtml = '<p data-mark="tracked"><strong>Important note.</strong></p>';
  const messages = buildDiyMessages({
    ...superdocsRequest(),
    scope: "selection",
    selectionHtml,
    selectionText: "Important note.",
    instruction: "Clarify this note",
  });
  assert.equal(DIY_PROMPT_VERSION, "diy-selection-context-v2");
  const userMessage = messages[1].content;
  assert.match(userMessage, /Prompt version: diy-selection-context-v2/);
  assert.match(userMessage, new RegExp(selectionHtml.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(userMessage, /DOCUMENT OUTLINE:\n\(no headings\)/);
  assert.match(userMessage, /NEARBY STRUCTURE/);
});

test("aggregates usage across initial and repair DIY completions", () => {
  assert.deepEqual(
    aggregateDiyUsage([
      { inputTokens: 100, outputTokens: 20, totalTokens: 120, hostedUsage: null },
      { inputTokens: 40, outputTokens: 10, totalTokens: 50, hostedUsage: null },
    ]),
    { inputTokens: 140, outputTokens: 30, totalTokens: 170, hostedUsage: null },
  );
  assert.deepEqual(
    aggregateDiyUsage([
      { inputTokens: 100, outputTokens: 20, totalTokens: 120, hostedUsage: null },
      { inputTokens: null, outputTokens: 10, totalTokens: null, hostedUsage: null },
    ]),
    { inputTokens: null, outputTokens: 30, totalTokens: null, hostedUsage: null },
  );
});

test("counts every DIY repair prompt payload in request metrics", () => {
  assert.deepEqual(
    aggregateDiyRequestMetrics([
      [
        { content: "system" },
        { content: "initial user prompt" },
      ],
      [
        { content: "system" },
        { content: "initial user prompt" },
        { content: "invalid response" },
        { content: "repair instruction" },
      ],
    ], 19),
    { promptChars: 84, contextChars: 38 },
  );
});

test("repairs malformed output at most once", async () => {
  let repairCalls = 0;
  const result = await parseWithOneRepair("not json", async () => {
    repairCalls += 1;
    return JSON.stringify({
      replacement_html: "<p>Repaired.</p>",
      explanation: "Valid on repair.",
    });
  });

  assert.equal(result.retryCount, 1);
  assert.equal(repairCalls, 1);
  assert.equal(result.parsed.replacement_html, "<p>Repaired.</p>");

  await assert.rejects(
    () =>
      parseWithOneRepair("bad", async () => {
        repairCalls += 1;
        return "still bad";
      }),
    /malformed JSON/,
  );
  assert.equal(repairCalls, 2);
});

test("rejects empty, executable, and oversized document HTML", () => {
  assert.throws(() => validateDocumentHtml("   "), /empty/);
  for (const unsafeHtml of [
    "<p>Safe</p><script>alert(1)</script>",
    '<p><img src=x onerror="alert(1)"></p>',
    '<a href="javascript:alert(1)">Unsafe</a>',
    '<a href="&#106;avascript:alert(1)">Unsafe</a>',
    '<a href="java\nscript:alert(1)">Unsafe</a>',
    "<p/onmouseover=alert(1)>Unsafe</p>",
    "<a/href=javascript:alert(1)>Unsafe</a>",
  ]) {
    const sanitized = validateDocumentHtml(unsafeHtml);
    assert.doesNotMatch(sanitized, /(?:javascript:|onerror|onmouseover|<script|<img)/i);
  }
  assert.throws(
    () => validateDocumentHtml(`<p>${"x".repeat(200_001)}</p>`),
    /safety limit/,
  );
  assert.doesNotThrow(() =>
    validateDocumentHtml('<p data-chunk-id="intro">Safe</p>'),
  );
});

test("reports SuperDocs as missing only when its server key is absent", () => {
  assert.deepEqual(getSuperdocsPublicConfig({}), {
    configured: false,
    modelTier: "core",
    thinkingDepth: "balanced",
    modelLabel: "core · balanced",
  });
  assert.deepEqual(
    getSuperdocsPublicConfig({
      SUPERDOCS_API_KEY: "server-only",
      SUPERDOCS_MODEL_TIER: "max",
      SUPERDOCS_THINKING_DEPTH: "deep",
    }),
    {
      configured: true,
      modelTier: "max",
      thinkingDepth: "deep",
      modelLabel: "max · deep",
    },
  );
});

test("starts an async hosted review and normalizes a chunk proposal", async () => {
  const calls = [];
  const engine = new SuperdocsEngine({
    env: {
      SUPERDOCS_API_KEY: "server-only",
      SUPERDOCS_POLL_ATTEMPTS: "1",
      SUPERDOCS_MODEL_TIER: "pro",
      SUPERDOCS_THINKING_DEPTH: "deep",
    },
    sleep: async () => {},
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      if (calls.length === 1) {
        return jsonResponse({
          job_id: "job-1",
          session_id: "session-1",
          status: "pending",
        });
      }
      return jsonResponse({
        status: "awaiting_approval",
        metadata: {
          pending_changes: [
            {
              change_id: "change-1",
              operation: "edit",
              chunk_id: "intro",
              old_html: '<p data-chunk-id="intro">Original.</p>',
              new_html: '<p data-chunk-id="intro">Clearer.</p>',
              ai_explanation: "Improved clarity.",
            },
          ],
        },
      });
    },
  });

  const result = await engine.edit(superdocsRequest());
  assert.equal(calls[0].url, "https://api.superdocs.app/v1/chat/async");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    message: "Make this clearer.",
    session_id: "lab-request-1",
    document_html: '<p data-chunk-id="intro">Original.</p>',
    approval_mode: "ask_every_time",
    model_tier: "pro",
    thinking_depth: "deep",
  });
  assert.equal(calls[1].url, "https://api.superdocs.app/v1/jobs/job-1");
  assert.equal(result.review?.state, "awaiting_approval");
  assert.equal(result.proposedChanges[0].chunkId, "intro");
  assert.equal(result.proposedChanges[0].newHtml, '<p data-chunk-id="intro">Clearer.</p>');
});

test("proxies approval then returns the completed hosted document state", async () => {
  const calls = [];
  const engine = new SuperdocsEngine({
    env: { SUPERDOCS_API_KEY: "server-only", SUPERDOCS_POLL_ATTEMPTS: "1" },
    sleep: async () => {},
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      if (calls.length === 1) {
        return jsonResponse({ job_id: "job-2", session_id: "session-2" });
      }
      if (calls.length === 2) {
        return jsonResponse({
          status: "awaiting_approval",
          metadata: {
            pending_changes: [
              {
                change_id: "change-2",
                operation: "edit",
                chunk_id: "intro",
                old_html: '<p data-chunk-id="intro">Original.</p>',
                new_html: '<p data-chunk-id="intro">Approved.</p>',
              },
            ],
          },
        });
      }
      if (calls.length === 3) return jsonResponse({ status: "in_progress" });
      return jsonResponse({
        status: "completed",
        result: {
          response: "Applied.",
          document_changes: {
            updated_html: '<p data-chunk-id="intro">Approved.</p>',
          },
          usage: { monthly_remaining: 99 },
        },
      });
    },
  });

  const pending = await engine.edit(superdocsRequest());
  const completed = await engine.decideReview({
    reviewId: pending.review.reviewId,
    decision: "accept",
    changeIds: ["change-2"],
  });
  assert.equal(calls[2].url, "https://api.superdocs.app/v1/chat/session-2/approve");
  assert.deepEqual(JSON.parse(calls[2].init.body), {
    job_id: "job-2",
    approved: true,
    changes: [{ change_id: "change-2", approved: true }],
  });
  assert.equal(
    completed.candidateDocumentHtml,
    '<p data-chunk-id="intro">Approved.</p>',
  );
  assert.equal(completed.usage.inputTokens, null);
  assert.match(completed.usage.hostedUsage, /monthly_remaining/);
});

test("proxies a documented denial decision for every change in the batch", async () => {
  const calls = [];
  const engine = new SuperdocsEngine({
    env: { SUPERDOCS_API_KEY: "server-only", SUPERDOCS_POLL_ATTEMPTS: "1" },
    sleep: async () => {},
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      if (calls.length === 1) {
        return jsonResponse({ job_id: "job-deny", session_id: "session-deny" });
      }
      if (calls.length === 2) {
        return jsonResponse({
          status: "awaiting_approval",
          metadata: {
            pending_changes: [
              { change_id: "change-a", operation: "edit" },
              { change_id: "change-b", operation: "delete" },
            ],
          },
        });
      }
      if (calls.length === 3) return jsonResponse({ status: "in_progress" });
      return jsonResponse({
        status: "completed",
        result: { document_changes: { updated_html: '<p data-chunk-id="intro">Original.</p>' } },
      });
    },
  });
  const pending = await engine.edit(superdocsRequest());
  await engine.decideReview({
    reviewId: pending.review.reviewId,
    decision: "reject",
    changeIds: ["change-a", "change-b"],
  });
  assert.deepEqual(JSON.parse(calls[2].init.body), {
    job_id: "job-deny",
    approved: false,
    changes: [
      { change_id: "change-a", approved: false },
      { change_id: "change-b", approved: false },
    ],
  });
});

test("keeps the same review broker context for additional approval batches", async () => {
  const calls = [];
  const engine = new SuperdocsEngine({
    env: { SUPERDOCS_API_KEY: "server-only", SUPERDOCS_POLL_ATTEMPTS: "1" },
    sleep: async () => {},
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      if (calls.length === 1) {
        return jsonResponse({ job_id: "job-batches", session_id: "session-batches" });
      }
      if (calls.length === 2 || calls.length === 4) {
        return jsonResponse({
          status: "awaiting_approval",
          metadata: {
            pending_changes: [
              {
                change_id: calls.length === 2 ? "change-first" : "change-second",
                operation: "edit",
                new_html: '<p data-chunk-id="intro">Proposed.</p>',
              },
            ],
          },
        });
      }
      if (calls.length === 3 || calls.length === 5) {
        return jsonResponse({ status: "in_progress" });
      }
      return jsonResponse({
        status: "completed",
        result: {
          document_changes: {
            updated_html: '<p data-chunk-id="intro">Completed.</p>',
          },
        },
      });
    },
  });

  const first = await engine.edit(superdocsRequest());
  const second = await engine.decideReview({
    reviewId: first.review.reviewId,
    decision: "accept",
    changeIds: ["change-first"],
  });
  assert.equal(second.review.reviewId, first.review.reviewId);
  assert.equal(second.review.batchNumber, 2);

  const completed = await engine.decideReview({
    reviewId: second.review.reviewId,
    decision: "reject",
    changeIds: ["change-second"],
  });
  assert.equal(
    completed.candidateDocumentHtml,
    '<p data-chunk-id="intro">Completed.</p>',
  );
});

test("cancels an initial job when bounded polling expires", async () => {
  const calls = [];
  const engine = new SuperdocsEngine({
    env: { SUPERDOCS_API_KEY: "server-only", SUPERDOCS_POLL_ATTEMPTS: "1" },
    sleep: async () => {},
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      if (calls.length === 1) return jsonResponse({ job_id: "job-timeout" });
      if (calls.length === 2) return jsonResponse({ status: "in_progress" });
      return jsonResponse({ status: "cancelled" });
    },
  });
  await assert.rejects(() => engine.edit(superdocsRequest()), /job was cancelled/);
  assert.equal(calls[2].url, "https://api.superdocs.app/v1/jobs/job-timeout/cancel");
});

test("cancels and expires a post-decision review when its poll expires", async () => {
  const calls = [];
  const engine = new SuperdocsEngine({
    env: { SUPERDOCS_API_KEY: "server-only", SUPERDOCS_POLL_ATTEMPTS: "1" },
    sleep: async () => {},
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), init });
      if (calls.length === 1) return jsonResponse({ job_id: "job-after-decision" });
      if (calls.length === 2) {
        return jsonResponse({
          status: "awaiting_approval",
          metadata: { pending_changes: [{ change_id: "change-1", operation: "edit" }] },
        });
      }
      if (calls.length === 3 || calls.length === 4) {
        return jsonResponse({ status: "in_progress" });
      }
      return jsonResponse({ status: "cancelled" });
    },
  });
  const pending = await engine.edit(superdocsRequest());
  await assert.rejects(
    () =>
      engine.decideReview({
        reviewId: pending.review.reviewId,
        decision: "accept",
        changeIds: ["change-1"],
      }),
    /job was cancelled/,
  );
  assert.equal(
    calls[4].url,
    "https://api.superdocs.app/v1/jobs/job-after-decision/cancel",
  );
  await assert.rejects(
    () =>
      engine.cancelReview(pending.review.reviewId),
    /no longer available/,
  );
});

test("proxies cancellation and keeps sensitive provider errors out of messages", async () => {
  const cancelCalls = [];
  const cancellable = new SuperdocsEngine({
    env: { SUPERDOCS_API_KEY: "server-only", SUPERDOCS_POLL_ATTEMPTS: "1" },
    sleep: async () => {},
    fetchImpl: async (url, init) => {
      cancelCalls.push({ url: String(url), init });
      if (cancelCalls.length === 1) {
        return jsonResponse({ job_id: "job-3", session_id: "session-3" });
      }
      if (cancelCalls.length === 2) {
        return jsonResponse({
          status: "awaiting_approval",
          metadata: {
            pending_changes: [
              {
                change_id: "change-3",
                operation: "delete",
                old_html: '<p data-chunk-id="intro">Original.</p>',
              },
            ],
          },
        });
      }
      return jsonResponse({ status: "cancelled" });
    },
  });
  const pending = await cancellable.edit(superdocsRequest());
  const cancelled = await cancellable.cancelReview(pending.review.reviewId);
  assert.equal(cancelCalls[2].url, "https://api.superdocs.app/v1/jobs/job-3/cancel");
  assert.equal(cancelled.error, "Review cancelled.");

  const failing = new SuperdocsEngine({
    env: { SUPERDOCS_API_KEY: "server-only" },
    fetchImpl: async () =>
      jsonResponse({ message: "Bearer server-only must not escape" }, 401),
  });
  await assert.rejects(
    () => failing.edit(superdocsRequest()),
    (error) =>
      error instanceof Error &&
      error.message === "SuperDocs rejected the request. Check the server-side configuration." &&
      !error.message.includes("server-only"),
  );
});