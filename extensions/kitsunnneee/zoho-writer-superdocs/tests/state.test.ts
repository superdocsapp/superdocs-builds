// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from "vitest";
import { BrowserRunStateStore } from "../src/state";

describe("browser run-state persistence", () => {
  beforeEach(() => localStorage.clear());

  it("stores only validated opaque run context", () => {
    const store = new BrowserRunStateStore(localStorage);
    store.save({
      version: 1,
      sessionId: "session-1",
      jobId: "job-1",
      status: "awaiting_approval",
      awaitingKind: "continue_prompt",
    });

    expect(store.load()).toEqual({
      version: 1,
      sessionId: "session-1",
      jobId: "job-1",
      status: "awaiting_approval",
      awaitingKind: "continue_prompt",
    });
    expect(localStorage.getItem("superdocs.writer.active-run.v1")).not.toMatch(
      /document|instruction|credential|token|html/i,
    );
  });

  it("clears malformed or unsupported state", () => {
    localStorage.setItem(
      "superdocs.writer.active-run.v1",
      JSON.stringify({
        version: 1,
        sessionId: "session-1",
        jobId: "job-1",
        status: "completed",
        documentHtml: "<p>must not persist</p>",
      }),
    );
    const store = new BrowserRunStateStore(localStorage);
    expect(store.load()).toBeNull();
    expect(localStorage.length).toBe(0);
  });
});
