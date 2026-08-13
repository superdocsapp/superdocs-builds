import { describe, expect, it } from "vitest";
import type {
  ApprovalPayload,
  SuperDocsPort,
  WriterPort,
} from "../src/types";
import { MemoryRunStateStore, type RunStateStore } from "../src/state";
import {
  buildApprovalPayload,
  getHostWritebackBlock,
  ReviewWorkflow,
} from "../src/workflow";

const editChange = {
  change_id: "c1",
  operation: "edit",
  old_html: "<p>One</p>",
  new_html: "<p>One improved</p>",
};

class FakeWriter implements WriterPort {
  async initialize() {}
  async getSelectedHtml() {
    return "<p>One</p>";
  }
}

class FakeApi implements SuperDocsPort {
  polls: unknown[] = [];
  approvals: ApprovalPayload[] = [];
  continues: Array<{ sessionId: string; jobId: string; shouldContinue: boolean }> =
    [];
  uploads = 0;
  chats = 0;

  async upload() {
    this.uploads += 1;
    return { session_id: "session-1" };
  }
  async startChat() {
    this.chats += 1;
    return { job_id: "job-1", session_id: "session-1", status: "pending" };
  }
  async getJob() {
    const poll = this.polls.shift();
    if (poll instanceof Error) throw poll;
    if (!poll) throw new Error("No fake poll queued");
    return poll;
  }
  async approve(_sessionId: string, payload: ApprovalPayload) {
    this.approvals.push(payload);
    return { accepted: true };
  }
  async continueChat(
    sessionId: string,
    jobId: string,
    shouldContinue: boolean,
  ) {
    this.continues.push({ sessionId, jobId, shouldContinue });
    return { accepted: true };
  }
  async exportDocument() {
    return new Blob(["docx"]);
  }
}

const awaiting = (changes: unknown[]) => ({
  job_id: "job-1",
  session_id: "session-1",
  status: "awaiting_approval",
  metadata: { pending_changes: changes },
});

const workflowFor = (api: FakeApi, store?: RunStateStore) =>
  new ReviewWorkflow(new FakeWriter(), api, () => undefined, {
    intervalMs: 0,
    timeoutMs: 1000,
    maxConsecutiveErrors: 0,
  }, store);

describe("approval workflow", () => {
  it("includes the required top-level approved and mixed decisions", () => {
    expect(
      buildApprovalPayload("job-1", [
        { changeId: "c1", approved: true },
        { changeId: "c2", approved: false, feedback: "Keep this wording" },
      ]),
    ).toEqual({
      job_id: "job-1",
      approved: false,
      changes: [
        { change_id: "c1", approved: true },
        { change_id: "c2", approved: false, feedback: "Keep this wording" },
      ],
    });
  });

  it("supports repeated approval rounds", async () => {
    const api = new FakeApi();
    api.polls.push(
      awaiting([editChange]),
      awaiting([{ ...editChange, change_id: "c2" }]),
      { job_id: "job-1", status: "completed", result: {} },
    );
    const workflow = workflowFor(api);

    const started = await workflow.begin("Improve this");
    const roundTwo = await workflow.decideRound(started.sessionId, "job-1", [
      { changeId: "c1", approved: true },
    ]);
    const completed = await workflow.decideRound(started.sessionId, "job-1", [
      { changeId: "c2", approved: false },
    ]);

    expect(roundTwo.changes.map((change) => change.id)).toEqual(["c2"]);
    expect(completed.status).toBe("completed");
    expect(api.approvals).toHaveLength(2);
  });

  it("handles continue_prompt through the dedicated endpoint", async () => {
    const api = new FakeApi();
    api.polls.push(
      {
        job_id: "job-1",
        session_id: "session-1",
        status: "awaiting_approval",
        metadata: { awaiting_kind: "continue_prompt", pending_changes: [] },
      },
      { job_id: "job-1", status: "completed", result: {} },
    );
    const workflow = workflowFor(api);

    const started = await workflow.begin("Large edit");
    expect(started.job.awaitingKind).toBe("continue_prompt");
    const completed = await workflow.continueRound(
      started.sessionId,
      "job-1",
      true,
    );

    expect(api.continues).toEqual([
      { sessionId: started.sessionId, jobId: "job-1", shouldContinue: true },
    ]);
    expect(completed.status).toBe("completed");
    expect(api.approvals).toEqual([]);
  });

  it("resumes the same job after polling failure without a new billable run", async () => {
    const api = new FakeApi();
    api.polls.push(
      new Error("network unavailable"),
      awaiting([editChange]),
    );
    const workflow = workflowFor(api);

    await expect(workflow.begin("Improve this")).rejects.toThrow(
      "network unavailable",
    );
    expect(workflow.canResume()).toBe(true);
    const resumed = await workflow.resume();

    expect(resumed.status).toBe("awaiting_approval");
    expect(api.uploads).toBe(1);
    expect(api.chats).toBe(1);
  });

  it("restores the same awaiting job after a simulated reload", async () => {
    const api = new FakeApi();
    const store = new MemoryRunStateStore();
    api.polls.push(
      awaiting([editChange]),
      awaiting([editChange]),
    );
    const firstWorkflow = workflowFor(api, store);
    const started = await firstWorkflow.begin("Improve this");

    expect(store.state).toMatchObject({
      sessionId: started.sessionId,
      jobId: "job-1",
      status: "awaiting_approval",
    });
    expect(JSON.stringify(store.state)).not.toContain("<p>One</p>");
    expect(JSON.stringify(store.state)).not.toContain("Improve this");

    const reloadedWorkflow = workflowFor(api, store);
    const restored = await reloadedWorkflow.restore();

    expect(restored?.status).toBe("awaiting_approval");
    expect(reloadedWorkflow.getActiveContext()).toMatchObject({
      sessionId: started.sessionId,
      jobId: "job-1",
    });
    expect(api.uploads).toBe(1);
    expect(api.chats).toBe(1);
  });

  it("restores persisted continue-prompt context", async () => {
    const api = new FakeApi();
    const store = new MemoryRunStateStore();
    store.save({
      version: 1,
      sessionId: "session-persisted",
      jobId: "job-persisted",
      status: "awaiting_approval",
      awaitingKind: "continue_prompt",
    });
    api.polls.push({
      job_id: "job-persisted",
      session_id: "session-persisted",
      status: "awaiting_approval",
      metadata: { awaiting_kind: "continue_prompt", pending_changes: [] },
    });

    const workflow = workflowFor(api, store);
    const restored = await workflow.restore();
    expect(restored?.awaitingKind).toBe("continue_prompt");
    expect(workflow.getActiveContext().awaitingKind).toBe("continue_prompt");
  });

  it("does not offer resume before a job ID exists", async () => {
    const api = new FakeApi();
    api.startChat = async () => {
      api.chats += 1;
      throw new Error("chat request failed before job ID");
    };
    const workflow = workflowFor(api);
    await expect(workflow.begin("Improve this")).rejects.toThrow("before job ID");
    expect(workflow.canResume()).toBe(false);
    await expect(workflow.resume()).rejects.toThrow("No existing job");
  });
});

describe("host writeback policy", () => {
  it("disables edit writeback pending live Sigma capability verification", () => {
    expect(
      getHostWritebackBlock([
        {
          id: "c1",
          operation: "edit",
          oldHtml: "<p>Zoho</p>",
          newHtml: "<p>SuperDocs structural HTML</p>",
          explanation: "",
        },
      ]),
    ).toContain("disabled until live Sigma testing");
  });

  it.each([
    {
      id: "create",
      operation: "create" as const,
      oldHtml: "",
      newHtml: "<p>new</p>",
      explanation: "",
    },
    {
      id: "delete",
      operation: "delete" as const,
      oldHtml: "<p>old</p>",
      newHtml: "",
      explanation: "",
    },
    {
      id: "insert",
      operation: "edit" as const,
      insertAfterChunkId: "chunk-1",
      oldHtml: "",
      newHtml: "<p>new</p>",
      explanation: "",
    },
  ])("explicitly blocks structural writeback for $id", (change) => {
    expect(getHostWritebackBlock([change])).toContain(
      "requires a verified chunk/range API",
    );
  });
});
