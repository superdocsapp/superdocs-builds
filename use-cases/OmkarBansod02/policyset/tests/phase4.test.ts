import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it, vi } from "vitest";

import { generatePolicyWorkspace } from "@/app/policyset/generate-workspace";
import { applyPolicyEditOutcome } from "@/app/policyset/workspace-edit";
import { NORTHSTAR_GOODS_PROFILE } from "@/domain";
import {
  PolicySetSuperDocsSafetyError,
  SuperDocsClient,
  assertPendingChangesTargetDocument,
  startPolicyDocumentEdit,
  submitPolicyDocumentReview,
} from "@/superdocs";

describe("Phase 4 browser boundary", () => {
  it("keeps the SuperDocs API key and server adapter out of browser modules", () => {
    const clientDirectory = join(process.cwd(), "src/app/policyset");
    const browserSources = readdirSync(clientDirectory)
      .filter((filename) => /\.(ts|tsx)$/.test(filename))
      .map((filename) => readFileSync(join(clientDirectory, filename), "utf8"))
      .join("\n");

    expect(browserSources).not.toContain("SUPERDOCS_API_KEY");
    expect(browserSources).not.toMatch(/from ["']@\/superdocs(?:\/|["'])/);
  });
});

describe("Phase 4 selected-document editing", () => {
  it("pins the edit request to the selected document_id", async () => {
    let requestBody: unknown;
    const client = new SuperDocsClient({
      apiKey: "server-only-test-key",
      fetch: async (_input, init) => {
        requestBody = JSON.parse(String(init?.body));
        return jsonResponse({
          job_id: "job-warranty",
          session_id: "session-1",
          status: "pending",
        });
      },
    });

    await startPolicyDocumentEdit(
      {
        sessionId: "session-1",
        documentId: "doc-warranty",
        instruction: "Clarify the claim instructions.",
      },
      client,
    );

    expect(requestBody).toMatchObject({
      session_id: "session-1",
      document_id: "doc-warranty",
      approval_mode: "ask_every_time",
      response_mode: "full",
    });
  });

  it("fails closed when any proposal targets another document", () => {
    expect(() =>
      assertPendingChangesTargetDocument(
        [
          { documentId: "doc-warranty" },
          { documentId: "doc-returns" },
        ],
        "doc-warranty",
      ),
    ).toThrow(PolicySetSuperDocsSafetyError);
  });
});

describe("Phase 4 rejection", () => {
  it("denies every change explicitly and leaves displayed and canonical state unchanged", async () => {
    const submitReview = vi.fn(async () => ({
      status: "completed",
      batchComplete: true,
    }));
    const client = {
      getJob: vi.fn(async () => ({
        reference: {
          jobId: "job-warranty",
          sessionId: "session-1",
          status: "awaiting_approval" as const,
        },
        progress: 100,
        awaitingKind: null,
        pendingChanges: [
          pendingChange("change-1"),
          pendingChange("change-2"),
        ],
        errorCode: null,
      })),
      submitReview,
    } as unknown as NonNullable<
      Parameters<typeof submitPolicyDocumentReview>[1]
    >;

    const receipt = await submitPolicyDocumentReview(
      {
        jobId: "job-warranty",
        sessionId: "session-1",
        selectedDocumentId: "doc-warranty",
        approved: false,
      },
      client,
    );

    expect(receipt.decisionCount).toBe(2);
    expect(submitReview).toHaveBeenCalledWith({
      sessionId: "session-1",
      jobId: "job-warranty",
      decisions: [
        { changeId: "change-1", approved: false },
        { changeId: "change-2", approved: false },
      ],
    });

    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const rejected = applyPolicyEditOutcome(workspace, { kind: "rejected" });
    expect(rejected).toBe(workspace);
    expect(rejected.profile).toEqual(NORTHSTAR_GOODS_PROFILE);
    expect(rejected.documents).toEqual(workspace.documents);
  });
});

function pendingChange(changeId: string) {
  return {
    changeId,
    operation: "edit" as const,
    documentId: "doc-warranty",
    chunkId: null,
    oldHtml: "<p>Before</p>",
    newHtml: "<p>After</p>",
    aiExplanation: "Clarity edit",
  };
}

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
