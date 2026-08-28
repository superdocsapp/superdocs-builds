import { describe, expect, it, vi } from "vitest";
import { BridgeSession } from "../src/core/session";
import { SuperDocsClient } from "../src/core/client";
import { JobStatus } from "../src/core/types";
import * as fs from "fs";
import * as path from "path";

const FIX = path.join(__dirname, "fixtures");

function makeClient(overrides: { approve?: boolean } = {}): {
  client: SuperDocsClient;
  approvals: Record<string, unknown>[];
} {
  const awaiting = JSON.parse(fs.readFileSync(path.join(FIX, "job-awaiting.json"), "utf8")) as JobStatus;
  const done = JSON.parse(fs.readFileSync(path.join(FIX, "job-done.json"), "utf8")) as JobStatus;
  const approvals: Record<string, unknown>[] = [];
  let jobsPolled = 0;
  const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(url as string);
    if (u.pathname.startsWith("/v1/jobs/")) {
      jobsPolled += 1;
      return new Response(JSON.stringify(jobsPolled === 1 ? awaiting : done), { status: 200 });
    }
    if (u.pathname.endsWith("/approve")) {
      approvals.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({ status: "ok", batch_complete: true }), { status: 200 });
    }
    if (u.pathname === "/v1/chat/async") {
      return new Response(
        JSON.stringify({ job_id: awaiting.job_id, session_id: "s1", status: "pending" }),
        { status: 200 }
      );
    }
    throw new Error("unexpected " + u.pathname);
  }) as unknown as typeof fetch;
  const client = new SuperDocsClient("sk_test", {
    baseUrl: "https://api.superdocs.app",
    pollIntervalMs: 5,
    maxPollSeconds: 30,
    fetchImpl,
  });
  return { client, approvals };
}

describe("BridgeSession", () => {
  it("pauses for UI decisions and approves with the chosen subset", async () => {
    const { client, approvals } = makeClient();
    const events: string[] = [];
    const session = new BridgeSession(client, "s1", {
      opBudget: 5,
      pollIntervalMs: 5,
    }, (e) => events.push(e.type));

    const editPromise = session.requestEdit("tighten the abstract");
    // requestEdit blocks on the approval pause — let the poller run
    const timer = setInterval(() => {
      if (events.includes("awaiting_approval")) {
        session.submitDecisions([{ changeId: "c1", approved: true }]);
      }
    }, 10);

    const job = await editPromise;
    clearInterval(timer);

    expect(job.status).toBe("completed");
    expect(events).toContain("awaiting_approval");
    expect(events).toContain("approved");
    expect(approvals.length).toBe(1);
    expect(approvals[0]).toMatchObject({ approved: true });
    expect((approvals[0].changes as { change_id: string }[]).map((c) => c.change_id)).toContain("c1");
  });

  it("enforces the op budget", async () => {
    const { client } = makeClient();
    const session = new BridgeSession(client, "s1", { opBudget: 1, pollIntervalMs: 5 }, () => {});
    const timer = setInterval(() => {
      session.submitDecisions([{ changeId: "c1", approved: true }]);
    }, 10);
    const first = await session.requestEdit("first");
    clearInterval(timer);
    expect(first.status).toBe("completed");
    expect(session.remainingBudget).toBe(0);
    await expect(session.requestEdit("second")).rejects.toThrow(/budget/i);
  });
});
