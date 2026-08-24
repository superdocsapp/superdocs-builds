import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createDryRun,
  resumeRun,
  submitDecisions,
  type GoogleConnection,
  type RunView,
  type SourceRegistration,
} from "../app/lib/api";
import {
  buildReviewDecisionSubmission,
  routeRun,
} from "../app/lib/workspace-state";

const runId = "0d33d1cf-fb6e-4569-a54c-9a3c7ea9f5ce";

const connection: GoogleConnection = {
  connection_id: "connection-1",
  provider: "GOOGLE",
  status: "CONNECTED",
  granted_scopes: [],
  last_validated_at: null,
  disconnected_at: null,
};

const source: SourceRegistration = {
  source: {
    source_id: "source-1",
    provider_file_id: "file-1",
    name: "Contract",
    mime_type: "application/vnd.google-apps.document",
    parent_ids: [],
  },
  baseline: {
    capture_id: "capture-1",
    revision_id: "revision-1",
    native_canonical_sha256: "a".repeat(64),
    docx_sha256: "b".repeat(64),
    docx_size_bytes: 1,
  },
};

const awaitingReviewRun: RunView = {
  run_id: runId,
  source_id: source.source.source_id,
  provider_revision_id: source.baseline.revision_id,
  state: "AWAITING_REVIEW",
  attention_code: null,
  session_id: "session-1",
  session_document_id: "document-1",
  durable_document_id: null,
  upload_version_id: null,
  final_version_id: null,
  provider_job_id: "job-1",
  provider_job_status: "AWAITING_REVIEW",
  awaiting_kind: "REVIEW",
  pending_proposals: [{
    proposal_id: "proposal-1",
    review_round: 1,
    change_id: "change-1",
    operation: "replace",
    chunk_id: null,
    document_id: "document-1",
    old_html: "<p>45 days</p>",
    new_html: "<p>30 days</p>",
    ai_explanation: null,
    replaces_proposal_id: null,
    decision: null,
    feedback: null,
  }],
  export: null,
  write_back: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

afterEach(() => vi.unstubAllGlobals());

describe("resume → review → submit decisions", () => {
  it("sends every explicit safety retry through the dry-run API", async () => {
    const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
      void url;
      void options;
      return jsonResponse({ status: "UNSUPPORTED" });
    });
    vi.stubGlobal("fetch", fetchMock);

    await createDryRun(runId);
    await createDryRun(runId);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const call of fetchMock.mock.calls) {
      expect(call[0]).toBe(`http://localhost:8000/api/v1/runs/${runId}/dry-run`);
      expect(call[1]).toMatchObject({ method: "POST", body: "{}" });
    }
  });

  it("submits decisions to the authoritative run ID returned by resume", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith(`/runs/${runId}/resume`)) return jsonResponse(awaitingReviewRun);
      return jsonResponse({ ...awaitingReviewRun, state: "REVIEWED_EXPORT_READY" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const resumed = await resumeRun(runId);
    const reviewState = routeRun(connection, source, resumed);
    if (reviewState === "dry-run-needed") {
      throw new Error("Expected resume response to enter review");
    }
    expect(reviewState).not.toBe("dry-run-needed");
    expect(reviewState).toMatchObject({ stage: "review", run: { run_id: runId } });

    const submission = buildReviewDecisionSubmission(reviewState);
    expect(submission).toMatchObject({ runId });
    if (!submission) throw new Error("Expected resume response to produce review submission");

    await submitDecisions(submission.runId, submission.decisions);

    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `http://localhost:8000/api/v1/runs/${runId}/decisions`,
    );
  });

  it("formats FastAPI validation details without coercing objects to strings", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      detail: [{
        type: "uuid_parsing",
        loc: ["path", "run_id"],
        msg: "Input should be a valid UUID",
        input: "undefined",
      }],
    }, 422)));

    await expect(submitDecisions(runId, [])).rejects.toThrow(
      "path → run_id: Input should be a valid UUID",
    );
  });

  it("refuses to construct a decisions URL for an unavailable run ID", () => {
    expect(() => submitDecisions("undefined", [])).toThrow("current run ID is unavailable");
  });
});
