import { describe, expect, it } from "vitest";
import {
  type Action,
  type Candidate,
  canScan,
  counts,
  initial,
  ordered,
  reduce,
  revertBlocker,
  scanLabel,
  type State,
} from "./session";

type Found = Omit<Candidate, "status" | "batch">;

const found = (id: string, chunk: string, start: number, text: string): Found => ({
  id,
  key: `${chunk}:${start}:${text}`,
  category: "personal",
  kind: "ssn",
  detector: "pattern",
  text,
  sentence: `… ${text} …`,
  part_type: "body",
  chunk_id: chunk,
  char_start: start,
  char_end: start + text.length,
  marker: "[SSN REDACTED]",
});

const run = (state: State, ...actions: Action[]) => actions.reduce(reduce, state);

describe("the list a reviewer reads", () => {
  it("puts the newest scan on top and keeps document order inside it", () => {
    // Two findings in one paragraph, then the reviewer types and a third
    // appears. The new one belongs above both, not sorted in among them.
    const first = run(initial, { type: "scan:start" }, {
      type: "scan:done",
      found: [found("a", "c1", 10, "111-11-1111"), found("b", "c1", 40, "222-22-2222")],
    });
    const second = run(first, { type: "document:changed" }, { type: "scan:start" }, {
      type: "scan:done",
      found: [
        found("a", "c1", 10, "111-11-1111"),
        found("b", "c1", 40, "222-22-2222"),
        found("c", "c9", 0, "333-33-3333"),
      ],
    });

    expect(ordered(second).map((item) => item.id)).toEqual(["c", "a", "b"]);
  });

  it("adds only what is new, so answered rows keep their decisions", () => {
    const first = run(initial, { type: "scan:start" }, {
      type: "scan:done",
      found: [found("a", "c1", 10, "111-11-1111")],
    });
    const decided = run(first, { type: "decide", id: "a", status: "applied" });
    const again = run(decided, { type: "scan:start" }, {
      type: "scan:done",
      found: [found("a", "c1", 10, "111-11-1111"), found("b", "c2", 0, "222-22-2222")],
    });

    expect(again.candidates).toHaveLength(2);
    expect(again.candidates.find((item) => item.id === "a")?.status).toBe("applied");
    expect(again.newest).toEqual(["b"]);
  });

  it("scrolls to what just arrived, and to nothing when nothing did", () => {
    // `newest` is what the pane scrolls to. A re-scan that finds nothing new
    // must not yank the view somewhere.
    const first = run(initial, { type: "scan:start" }, {
      type: "scan:done",
      found: [found("a", "c1", 10, "111-11-1111")],
    });
    const same = run(first, { type: "scan:start" }, {
      type: "scan:done",
      found: [found("a", "c1", 10, "111-11-1111")],
    });

    expect(same.newest).toEqual([]);
  });

  it("keeps a decided row after its text is gone, and drops an unanswered one", () => {
    // Redacting the text means the next scan cannot find it. The record of the
    // decision outlives the text; an untouched candidate that vanished from the
    // document is just gone.
    const first = run(initial, { type: "scan:start" }, {
      type: "scan:done",
      found: [found("a", "c1", 0, "111-11-1111"), found("b", "c2", 0, "222-22-2222")],
    });
    const decided = run(first, { type: "decide", id: "a", status: "applied" });
    const after = run(decided, { type: "scan:start" }, { type: "scan:done", found: [] });

    expect(after.candidates.map((item) => item.id)).toEqual(["a"]);
  });
});

describe("a reloaded pane", () => {
  it("keeps the decisions the service already holds", () => {
    // Right-click → Reload inside Word throws away every bit of pane state. The
    // service still has the session, so a scan returns twelve candidates of
    // which four are answered — and re-asking those four is the failure.
    const reloaded = run(initial, { type: "scan:start" }, {
      type: "scan:done",
      found: [
        { ...found("a", "c1", 0, "111-11-1111"), status: "applied" },
        { ...found("b", "c1", 20, "222-22-2222"), status: "dismissed" },
        found("c", "c1", 40, "333-33-3333"),
      ],
    });

    expect(counts(reloaded)).toMatchObject({ redacted: 1, dismissed: 1, pending: 1 });
  });

  it("does not scroll to work that is already done", () => {
    const reloaded = run(initial, { type: "scan:start" }, {
      type: "scan:done",
      found: [
        { ...found("a", "c1", 0, "111-11-1111"), status: "applied" },
        found("c", "c1", 40, "333-33-3333"),
      ],
    });

    expect(reloaded.newest).toEqual(["c"]);
  });
});

describe("typing re-arms the scan", () => {
  it("marks the result stale and changes what the button says", () => {
    const scanned = run(initial, { type: "scan:start" }, { type: "scan:done", found: [] });
    expect(scanLabel(scanned)).toBe("Re-scan");
    expect(scanned.stale).toBe(false);

    const typed = run(scanned, { type: "document:changed" });

    expect(typed.stale).toBe(true);
    expect(scanLabel(typed)).toBe("Check for new");
    expect(canScan(typed)).toBe(true);
  });

  it("clears staleness only by scanning again", () => {
    const typed = run(
      initial,
      { type: "scan:start" },
      { type: "scan:done", found: [] },
      { type: "document:changed" },
      { type: "decide", id: "nothing", status: "dismissed" },
    );
    expect(typed.stale).toBe(true);

    const rescanned = run(typed, { type: "scan:start" }, { type: "scan:done", found: [] });
    expect(rescanned.stale).toBe(false);
  });

  it("does not offer a second scan while one is running", () => {
    const scanning = run(initial, { type: "scan:start" });
    expect(canScan(scanning)).toBe(false);
    expect(scanLabel(scanning)).toBe("Scanning…");
  });
});

describe("what the header counts", () => {
  it("separates redacted from dismissed from still waiting", () => {
    const state = run(
      initial,
      { type: "scan:start" },
      {
        type: "scan:done",
        found: [
          found("a", "c1", 0, "111-11-1111"),
          found("b", "c1", 20, "222-22-2222"),
          found("c", "c1", 40, "333-33-3333"),
        ],
      },
      { type: "decide", id: "a", status: "applied" },
      { type: "decide", id: "b", status: "dismissed" },
    );

    expect(counts(state)).toMatchObject({ total: 3, pending: 1, redacted: 1, dismissed: 1 });
  });
});

describe("putting a redaction back", () => {
  const applied = (id: string, text: string, marker: string, part = "body") => ({
    ...found(id, "c1", 0, text),
    marker,
    part_type: part,
  });

  const stateWith = (...items: ReturnType<typeof applied>[]): State =>
    run(initial, { type: "scan:start" }, { type: "scan:done", found: items });

  const allApplied = (state: State): State =>
    state.candidates.reduce(
      (acc, item) => reduce(acc, { type: "decide", id: item.id, status: "applied" }),
      state,
    );

  it("allows it when the marker in that part is unique", () => {
    const state = allApplied(
      stateWith(
        applied("a", "Margaret Hollis", "[NAME REDACTED]"),
        applied("b", "4111 1111 1111 1111", "[CREDIT CARD REDACTED]"),
      ),
    );

    expect(revertBlocker(state, state.candidates.find((c) => c.id === "a")!)).toBeNull();
  });

  it("refuses when two redactions in one part share a marker", () => {
    // The failure it exists to prevent: both are `[NAME REDACTED]`, so
    // restoring one would write Margaret's name where Dmitri's used to be.
    const state = allApplied(
      stateWith(
        applied("a", "Margaret Hollis", "[NAME REDACTED]"),
        applied("b", "Dmitri Sokolov", "[NAME REDACTED]"),
      ),
    );

    expect(revertBlocker(state, state.candidates.find((c) => c.id === "a")!)).toContain(
      "which one is which",
    );
  });

  it("allows it when the same marker is used in a different part", () => {
    // A name in the body and a name in a comment are separate stories; the
    // search for one never reaches the other.
    const state = allApplied(
      stateWith(
        applied("a", "Margaret Hollis", "[NAME REDACTED]", "body"),
        applied("b", "Dmitri Sokolov", "[NAME REDACTED]", "comment"),
      ),
    );

    expect(revertBlocker(state, state.candidates.find((c) => c.id === "a")!)).toBeNull();
  });

  it("always allows undoing a dismissal, which wrote nothing", () => {
    const state = run(
      stateWith(applied("a", "Margaret Hollis", "[NAME REDACTED]")),
      { type: "decide", id: "a", status: "dismissed" },
    );

    expect(revertBlocker(state, state.candidates[0])).toBeNull();
  });

  it("refuses an accepted tracked deletion, because Word cannot un-accept", () => {
    const state = allApplied(
      stateWith(applied("a", "Harold Vance", "[NAME REDACTED]", "tracked_del")),
    );

    expect(revertBlocker(state, state.candidates[0])).toContain("un-accept");
  });
});
