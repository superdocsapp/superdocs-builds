import { describe, expect, it } from "vitest";
import { InMemoryBackend } from "../src/persistence";
import { ReviewStore } from "../src/reviewStore";
import {
  extractTurn,
  findPrecedingUserInstruction,
  SessionWatcher,
  type SuperDocsReadPort,
} from "../src/sessionWatcher";
import type { JobDetail, PendingChange, SessionHistory } from "../src/superdocsClient";

function completedJob(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    job_id: "job_1",
    status: "completed",
    created_at: "2026-01-01T00:00:00.000Z",
    result: {
      response: "I've updated the title.",
      document_changes: { updated_html: '<h1 data-chunk-id="a">New</h1>' },
      usage: { was_billable: true, ops_charged: 1 },
    },
    ...overrides,
  };
}

/** Separate from `completedJob` on purpose: `result` is absent (not `undefined`-valued), which `exactOptionalPropertyTypes` treats differently from an explicit override. */
function hitlAwaitingApprovalJob(pending: PendingChange[]): JobDetail {
  return {
    job_id: "job_1",
    status: "awaiting_approval",
    created_at: "2026-01-01T00:00:00.000Z",
    metadata: { pending_changes: pending },
  };
}

describe("extractTurn", () => {
  it("builds a completed-job turn from result.document_changes.updated_html", () => {
    const extraction = extractTurn({
      job: completedJob(),
      sessionId: "s1",
      documentId: "doc1",
      clientType: "unknown",
      turnIndex: 1,
      previousHtml: '<h1 data-chunk-id="a">Old</h1>',
      claimedIntentText: "Update the title",
    });
    expect(extraction).not.toBeNull();
    expect(extraction?.turn.afterHtml).toBe('<h1 data-chunk-id="a">New</h1>');
    expect(extraction?.turn.wasBillable).toBe(true);
    expect(extraction?.diff).toHaveLength(1);
    expect(extraction?.hitlPending).toBeNull();
  });

  it("returns null for a job still in flight — nothing to ingest yet", () => {
    const inFlightJob: JobDetail = { job_id: "job_1", status: "in_progress", created_at: "2026-01-01T00:00:00.000Z" };
    const extraction = extractTurn({
      job: inFlightJob,
      sessionId: "s1",
      documentId: "doc1",
      clientType: "unknown",
      turnIndex: 1,
      previousHtml: "<p>x</p>",
      claimedIntentText: "",
    });
    expect(extraction).toBeNull();
  });

  it("surfaces HITL pending_changes without applying anything (document unchanged)", () => {
    const extraction = extractTurn({
      job: hitlAwaitingApprovalJob([
        {
          change_id: "ch_1",
          operation: "edit",
          chunk_id: "a",
          old_html: '<h1 data-chunk-id="a">Old</h1>',
          new_html: '<h1 data-chunk-id="a">New</h1>',
          ai_explanation: "Updating the title.",
          insert_after_chunk_id: null,
        },
      ]),
      sessionId: "s1",
      documentId: "doc1",
      clientType: "unknown",
      turnIndex: 1,
      previousHtml: '<h1 data-chunk-id="a">Old</h1>',
      claimedIntentText: "Update the title",
    });
    expect(extraction?.hitlPending).toHaveLength(1);
    expect(extraction?.turn.beforeHtml).toBe(extraction?.turn.afterHtml); // unapplied
    expect(extraction?.diff).toEqual([]);
  });
});

describe("findPrecedingUserInstruction", () => {
  const messages: SessionHistory["messages"] = [
    { role: "user", content: "Update the title.", turn_index: 1, checkpoint_id: "c1" },
    { role: "assistant", content: "I've updated the title.", turn_index: 1, checkpoint_id: "c1" },
    { role: "user", content: "Now update the intro.", turn_index: 2, checkpoint_id: "c2" },
    { role: "assistant", content: "I've updated the intro.", turn_index: 2, checkpoint_id: "c2" },
  ];

  it("finds the user message that precedes a matching assistant reply, by content", () => {
    expect(findPrecedingUserInstruction(messages, "I've updated the intro.")).toBe("Now update the intro.");
    expect(findPrecedingUserInstruction(messages, "I've updated the title.")).toBe("Update the title.");
  });

  it("returns empty string rather than guessing when the reply text isn't found", () => {
    expect(findPrecedingUserInstruction(messages, "no such reply exists")).toBe("");
  });

  it("returns empty string for an empty reply", () => {
    expect(findPrecedingUserInstruction(messages, "")).toBe("");
  });
});

describe("buildTurn — turn identity rests on the server job_id, not a local counter", () => {
  it("two extractions of the same job_id produce the same turnId even with different local turnIndex values", () => {
    const first = extractTurn({
      job: completedJob({ job_id: "job_abc" }),
      sessionId: "s1",
      documentId: "s1",
      clientType: "unknown",
      turnIndex: 1, // as if this were the 1st turn processed
      previousHtml: '<h1 data-chunk-id="a">Old</h1>',
      claimedIntentText: "",
    });
    const second = extractTurn({
      job: completedJob({ job_id: "job_abc" }),
      sessionId: "s1",
      documentId: "s1",
      clientType: "unknown",
      turnIndex: 7, // as if a cursor recovery/bug assigned a different local index
      previousHtml: '<h1 data-chunk-id="a">Old</h1>',
      claimedIntentText: "",
    });
    // Same server job -> same turn identity, regardless of local turnIndex
    // bookkeeping — this is what makes "same job twice = one logical
    // event" true by construction, not just by careful cursor management.
    expect(first?.turn.turnId).toBe(second?.turn.turnId);
    expect(first?.turn.turnId).toBe("s1:job_abc");
  });
});

class FakeReadPort implements SuperDocsReadPort {
  sessions: { session_id: string; last_activity: string }[] = [];
  jobsBySession = new Map<string, { job_id: string; status: string; created_at?: string }[]>();
  jobDetails = new Map<string, JobDetail>();
  history = new Map<string, SessionHistory>();
  listSessionsCalls = 0;
  failNextListSessionJobsWith: unknown = null;

  async listSessions() {
    this.listSessionsCalls += 1;
    return this.sessions;
  }
  async listSessionJobs(sessionId: string) {
    if (this.failNextListSessionJobsWith) {
      const err = this.failNextListSessionJobsWith;
      this.failNextListSessionJobsWith = null;
      throw err;
    }
    return this.jobsBySession.get(sessionId) ?? [];
  }
  async getJob(jobId: string) {
    const job = this.jobDetails.get(jobId);
    if (!job) throw new Error(`no fake job registered for ${jobId}`);
    return job;
  }
  async getSessionHistory(sessionId: string) {
    return this.history.get(sessionId) ?? { messages: [], document_state: null };
  }
}

function freshStore(persistence = new InMemoryBackend()) {
  return new ReviewStore(persistence, { decideHitlChange: async () => {}, applyPatch: async () => {} });
}

/**
 * Establishes a session's baseline with no jobs yet (the realistic case:
 * you connect and start watching before the interesting activity happens),
 * so tests that aren't specifically about bootstrap behavior aren't
 * incidentally exercising it.
 */
async function primeSession(port: FakeReadPort, watcher: SessionWatcher, sessionId: string): Promise<void> {
  if (!port.jobsBySession.has(sessionId)) port.jobsBySession.set(sessionId, []);
  if (!port.sessions.some((s) => s.session_id === sessionId)) {
    port.sessions = [...port.sessions, { session_id: sessionId, last_activity: "t" }];
  }
  await watcher.pollOnce();
}

describe("SessionWatcher — bootstrap baseline (a session already has history before the watcher starts)", () => {
  it("does not report a session's pre-existing, already-completed job as a newly-created change", async () => {
    const port = new FakeReadPort();
    port.sessions = [{ session_id: "s1", last_activity: "t" }];
    // This job already completed before the watcher ever looked at "s1" —
    // simulating a document that already had content before being observed.
    port.jobsBySession.set("s1", [{ job_id: "job_0", status: "completed", created_at: "2026-01-01T00:00:00.000Z" }]);
    port.jobDetails.set(
      "job_0",
      completedJob({
        job_id: "job_0",
        result: {
          response: "irrelevant — this predates watching",
          document_changes: {
            updated_html:
              '<h1 data-chunk-id="a">Pre-existing Title</h1><p data-chunk-id="b">Pre-existing paragraph.</p>',
          },
          usage: { was_billable: true, ops_charged: 1 },
        },
      })
    );

    const store = freshStore();
    const watcher = new SessionWatcher(port, store);
    await watcher.pollOnce(); // first-ever sight of "s1"

    // The bug this guards against: diffing job_0 against an empty baseline
    // would report the entire pre-existing document as newly created.
    expect(store.listAllChanges()).toHaveLength(0);
  });

  it("correctly diffs the first genuinely NEW job against the bootstrapped baseline, not against empty", async () => {
    const port = new FakeReadPort();
    port.sessions = [{ session_id: "s1", last_activity: "t" }];
    port.jobsBySession.set("s1", [{ job_id: "job_0", status: "completed", created_at: "2026-01-01T00:00:00.000Z" }]);
    port.jobDetails.set(
      "job_0",
      completedJob({
        job_id: "job_0",
        result: {
          response: "pre-existing",
          document_changes: {
            updated_html: '<h1 data-chunk-id="a">Title</h1><p data-chunk-id="b">Original paragraph.</p>',
          },
          usage: { was_billable: true, ops_charged: 1 },
        },
      })
    );

    const store = freshStore();
    const watcher = new SessionWatcher(port, store);
    await watcher.pollOnce(); // bootstrap: job_0 silently accounted for
    expect(store.listAllChanges()).toHaveLength(0);

    // A genuinely new job arrives after bootstrap.
    port.jobsBySession.set("s1", [
      { job_id: "job_0", status: "completed", created_at: "2026-01-01T00:00:00.000Z" },
      { job_id: "job_1", status: "completed", created_at: "2026-01-01T00:01:00.000Z" },
    ]);
    port.jobDetails.set(
      "job_1",
      completedJob({
        job_id: "job_1",
        created_at: "2026-01-01T00:01:00.000Z",
        result: {
          response: "I've updated the paragraph.",
          document_changes: {
            updated_html: '<h1 data-chunk-id="a">Title</h1><p data-chunk-id="b">Updated paragraph.</p>',
          },
          usage: { was_billable: true, ops_charged: 1 },
        },
      })
    );
    await watcher.pollOnce();

    // Exactly one change — the paragraph edit — not the title "changing"
    // from nothing, and not the whole document re-reported.
    const changes = store.listAllChanges();
    expect(changes).toHaveLength(1);
    expect(changes[0]?.chunkId).toBe("b");
    expect(changes[0]?.beforeHtml).toBe('<p data-chunk-id="b">Original paragraph.</p>');
    expect(changes[0]?.afterHtml).toBe('<p data-chunk-id="b">Updated paragraph.</p>');
  });

  it("still surfaces a HITL job awaiting approval even if it existed before the watcher started", async () => {
    const port = new FakeReadPort();
    port.sessions = [{ session_id: "s1", last_activity: "t" }];
    // This job is NOT completed — it's a live, pending decision right now,
    // regardless of when the watcher started looking.
    port.jobsBySession.set("s1", [{ job_id: "job_0", status: "awaiting_approval", created_at: "2026-01-01T00:00:00.000Z" }]);
    port.jobDetails.set(
      "job_0",
      hitlAwaitingApprovalJob([
        {
          change_id: "ch_1",
          operation: "edit",
          chunk_id: "a",
          old_html: "<p>old</p>",
          new_html: "<p>new</p>",
          ai_explanation: "Editing.",
          insert_after_chunk_id: null,
        },
      ])
    );

    const store = freshStore();
    const watcher = new SessionWatcher(port, store);
    await watcher.pollOnce();

    expect(store.listAllChanges()).toHaveLength(1);
    expect(store.listAllChanges()[0]?.status).toBe("proposed");
  });
});

describe("SessionWatcher.pollOnce", () => {
  it("ingests a new completed job into the review store", async () => {
    const port = new FakeReadPort();
    const store = freshStore();
    const watcher = new SessionWatcher(port, store);
    await primeSession(port, watcher, "s1"); // establish baseline before the job under test appears

    port.jobsBySession.set("s1", [{ job_id: "job_1", status: "completed", created_at: "2026-01-01T00:00:00.000Z" }]);
    port.jobDetails.set("job_1", completedJob());
    await watcher.pollOnce();

    expect(store.listAllChanges()).toHaveLength(1);
    expect(store.listAllChanges()[0]?.chunkId).toBe("a");
  });

  it("does not re-ingest a job already processed on a later poll", async () => {
    const port = new FakeReadPort();
    const store = freshStore();
    const watcher = new SessionWatcher(port, store);
    await primeSession(port, watcher, "s1");

    port.jobsBySession.set("s1", [{ job_id: "job_1", status: "completed", created_at: "2026-01-01T00:00:00.000Z" }]);
    port.jobDetails.set("job_1", completedJob());
    await watcher.pollOnce();
    await watcher.pollOnce();

    expect(store.listAllChanges()).toHaveLength(1);
  });

  it("re-checks an awaiting_approval job on every poll until it resolves", async () => {
    const port = new FakeReadPort();
    port.sessions = [{ session_id: "s1", last_activity: "t" }];
    port.jobsBySession.set("s1", [{ job_id: "job_1", status: "awaiting_approval", created_at: "2026-01-01T00:00:00.000Z" }]);
    port.jobDetails.set(
      "job_1",
      hitlAwaitingApprovalJob([
        {
          change_id: "ch_1",
          operation: "edit",
          chunk_id: "a",
          old_html: "<p>old</p>",
          new_html: "<p>new</p>",
          ai_explanation: "Editing.",
          insert_after_chunk_id: null,
        },
      ])
    );

    const store = freshStore();
    const watcher = new SessionWatcher(port, store);
    await watcher.pollOnce();
    await watcher.pollOnce();

    expect(store.listAllChanges()).toHaveLength(1);
    expect(store.listAllChanges()[0]?.status).toBe("proposed");
  });

  it("processes jobs in creation-time order even if the API returns them out of order", async () => {
    const port = new FakeReadPort();
    const store = freshStore();
    const watcher = new SessionWatcher(port, store);
    await primeSession(port, watcher, "s1");

    // Deliberately returned newest-first — the watcher must not trust this order.
    port.jobsBySession.set("s1", [
      { job_id: "job_2", status: "completed", created_at: "2026-01-01T00:01:00.000Z" },
      { job_id: "job_1", status: "completed", created_at: "2026-01-01T00:00:00.000Z" },
    ]);
    port.jobDetails.set(
      "job_1",
      completedJob({
        job_id: "job_1",
        created_at: "2026-01-01T00:00:00.000Z",
        result: {
          response: "first edit",
          document_changes: { updated_html: '<p data-chunk-id="a">first</p>' },
          usage: { was_billable: true, ops_charged: 1 },
        },
      })
    );
    port.jobDetails.set(
      "job_2",
      completedJob({
        job_id: "job_2",
        created_at: "2026-01-01T00:01:00.000Z",
        result: {
          response: "second edit",
          document_changes: { updated_html: '<p data-chunk-id="a">second</p>' },
          usage: { was_billable: true, ops_charged: 1 },
        },
      })
    );
    await watcher.pollOnce();

    const changes = store.listAllChanges().sort((a, b) => a.turnId.localeCompare(b.turnId));
    // Processed in creation order: the first change is job_1 ("" -> "first",
    // against the empty-but-legitimate primed baseline), the second is
    // job_2 ("first" -> "second") — not diffed against the wrong baseline,
    // which out-of-order processing would cause.
    expect(changes).toHaveLength(2);
    expect(changes[0]?.afterHtml).toBe('<p data-chunk-id="a">first</p>');
    expect(changes[1]?.beforeHtml).toBe('<p data-chunk-id="a">first</p>');
    expect(changes[1]?.afterHtml).toBe('<p data-chunk-id="a">second</p>');
  });

  it("never runs two polls concurrently — a slow tick is skipped, not overlapped", async () => {
    const port = new FakeReadPort();
    port.sessions = [{ session_id: "s1", last_activity: "t" }];
    let resolveListSessions: (() => void) | undefined;
    const originalListSessions = port.listSessions.bind(port);
    port.listSessions = () =>
      new Promise((resolve) => {
        resolveListSessions = () => resolve(originalListSessions());
      });

    const store = freshStore();
    const watcher = new SessionWatcher(port, store);

    const firstPoll = watcher.pollOnce(); // hangs until resolveListSessions() is called
    const secondPoll = watcher.pollOnce(); // should return immediately (overlap guard), not queue

    await secondPoll; // must resolve without needing resolveListSessions()
    expect(port.listSessionsCalls).toBe(0); // first poll's call hasn't even returned yet

    resolveListSessions?.();
    await firstPoll;
    expect(port.listSessionsCalls).toBe(1); // exactly one real call happened, not two
  });

  it("pauses polling for Retry-After seconds after a 429, then resumes", async () => {
    const port = new FakeReadPort();
    const store = freshStore();
    let now = 1_000_000;
    const watcher = new SessionWatcher(port, store, { now: () => now, onError: () => {} });
    await primeSession(port, watcher, "s1");

    port.jobsBySession.set("s1", [{ job_id: "job_1", status: "completed", created_at: "2026-01-01T00:00:00.000Z" }]);
    port.jobDetails.set("job_1", completedJob());
    port.failNextListSessionJobsWith = { status: 429, retryAfterSeconds: 30, message: "rate limited" };

    await watcher.pollOnce(); // hits the 429, pauses for 30s
    expect(store.listAllChanges()).toHaveLength(0);

    now += 10_000; // only 10s later — still paused
    await watcher.pollOnce();
    expect(store.listAllChanges()).toHaveLength(0);

    now += 25_000; // now 35s after the 429 — past the pause window
    await watcher.pollOnce();
    expect(store.listAllChanges()).toHaveLength(1);
  });

  it("isolates a failure in one session so other sessions still get processed", async () => {
    const port = new FakeReadPort();
    const store = freshStore();
    const errors: unknown[] = [];
    const watcher = new SessionWatcher(port, store, { onError: (err) => errors.push(err) });
    await primeSession(port, watcher, "healthy");

    port.sessions = [
      { session_id: "broken", last_activity: "t" },
      { session_id: "healthy", last_activity: "t" },
    ];
    port.jobsBySession.set("healthy", [{ job_id: "job_1", status: "completed", created_at: "2026-01-01T00:00:00.000Z" }]);
    port.jobDetails.set("job_1", completedJob());

    const originalListSessionJobs = port.listSessionJobs.bind(port);
    port.listSessionJobs = async (sessionId: string) => {
      if (sessionId === "broken") throw new Error("boom");
      return originalListSessionJobs(sessionId);
    };

    await watcher.pollOnce();

    expect(errors).toHaveLength(1);
    expect(store.listAllChanges()).toHaveLength(1); // "healthy" still got processed
  });

  it("passes the correlated user instruction through as claimedIntentText", async () => {
    const port = new FakeReadPort();
    const store = freshStore();
    const watcher = new SessionWatcher(port, store);
    await primeSession(port, watcher, "s1");

    port.jobsBySession.set("s1", [{ job_id: "job_1", status: "completed", created_at: "2026-01-01T00:00:00.000Z" }]);
    port.jobDetails.set(
      "job_1",
      completedJob({
        result: {
          response: "I've updated the title.",
          document_changes: { updated_html: '<h1 data-chunk-id="a">New</h1>' },
          usage: { was_billable: true, ops_charged: 1 },
        },
      })
    );
    port.history.set("s1", {
      messages: [
        { role: "user", content: "Please change the title.", turn_index: 1, checkpoint_id: null },
        { role: "assistant", content: "I've updated the title.", turn_index: 1, checkpoint_id: null },
      ],
      document_state: null,
    });

    await watcher.pollOnce();

    // claimedIntentText isn't stored on Change directly (it's turn-level),
    // but ingestion only succeeds via extractTurn, which is exercised above
    // in isolation — this test confirms the watcher actually calls
    // getSessionHistory and doesn't crash wiring it through end-to-end.
    expect(store.listAllChanges()).toHaveLength(1);
  });

  it("persists cursors so a fresh watcher instance against the same backend does not reprocess jobs", async () => {
    const port = new FakeReadPort();
    const persistence = new InMemoryBackend();
    const store = freshStore(persistence);
    const firstWatcher = new SessionWatcher(port, store, { persistence });
    await primeSession(port, firstWatcher, "s1");

    port.jobsBySession.set("s1", [{ job_id: "job_1", status: "completed", created_at: "2026-01-01T00:00:00.000Z" }]);
    port.jobDetails.set("job_1", completedJob());
    await firstWatcher.pollOnce();
    expect(store.listAllChanges()).toHaveLength(1);

    // Simulate an extension restart: brand new SessionWatcher instance,
    // same persistence backend and store.
    const secondWatcher = new SessionWatcher(port, store, { persistence });
    await secondWatcher.pollOnce();
    expect(store.listAllChanges()).toHaveLength(1); // not reprocessed into a duplicate turn
  });

  it("isolates a job with duplicate chunk ids: reports it, skips it, but keeps later jobs correctly diffed", async () => {
    const port = new FakeReadPort();
    const store = freshStore();
    const errors: unknown[] = [];
    const watcher = new SessionWatcher(port, store, { onError: (err) => errors.push(err) });
    await primeSession(port, watcher, "s1");

    port.jobsBySession.set("s1", [
      { job_id: "job_bad", status: "completed", created_at: "2026-01-01T00:00:00.000Z" },
    ]);
    port.jobDetails.set(
      "job_bad",
      completedJob({
        job_id: "job_bad",
        result: {
          response: "malformed turn",
          // Duplicate data-chunk-id="a" — cannot be safely diffed.
          document_changes: { updated_html: '<p data-chunk-id="a">one</p><p data-chunk-id="a">two</p>' },
          usage: { was_billable: true, ops_charged: 1 },
        },
      })
    );

    await watcher.pollOnce();

    // The bad job produced no Change (never silently guess at a diff)...
    expect(errors).toHaveLength(1);
    expect(store.listAllChanges()).toHaveLength(0);

    // A later, unrelated-looking edit is *also* flagged rather than
    // silently treated as safe: the baseline itself is still the
    // contaminated document, so any diff computed against it would be
    // built on a foundation already known to be unreliable — "looks
    // unrelated" is not the same as "provably safe." This is a deliberate
    // conservative trade-off: the session stays flagged rather than
    // silently recovering. See docs/GAP_ANALYSIS.md for the corresponding
    // limitation (recovering currently has no dedicated UI action).
    port.jobsBySession.set("s1", [
      { job_id: "job_bad", status: "completed", created_at: "2026-01-01T00:00:00.000Z" },
      { job_id: "job_next", status: "completed", created_at: "2026-01-01T00:02:00.000Z" },
    ]);
    port.jobDetails.set(
      "job_next",
      completedJob({
        job_id: "job_next",
        created_at: "2026-01-01T00:02:00.000Z",
        result: {
          response: "another edit",
          document_changes: { updated_html: '<h1 data-chunk-id="b">new heading</h1>' },
          usage: { was_billable: true, ops_charged: 1 },
        },
      })
    );
    await watcher.pollOnce();
    expect(errors).toHaveLength(2); // flagged again, not silently accepted
    expect(store.listAllChanges()).toHaveLength(0); // still no Change created
  });
});
