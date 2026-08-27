import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SelectionMovedError,
  ZohoWriterAdapter,
  resetHostCapabilityProbe,
} from "../src/writer";

const DOCUMENT_READS = ["DocumentContent", "GetDocumentContent", "Content"];

describe("ZohoWriterAdapter", () => {
  // The document-read probe is cached per page session, so it must be cleared
  // between tests or one host's capabilities leak into the next.
  afterEach(() => {
    resetHostCapabilityProbe();
  });

  it("uses the service client returned by Sigma initialization", async () => {
    const dispatch = vi.fn().mockResolvedValue("<p>Selected text</p>");
    const initialize = vi.fn().mockResolvedValue(undefined);
    const adapter = new ZohoWriterAdapter(initialize, () => ({
      dispatch,
      request: vi.fn(),
    }));

    await expect(adapter.getSelectedHtml()).resolves.toBe(
      "<p>Selected text</p>",
    );
    expect(initialize).toHaveBeenCalledOnce();
    expect(dispatch).toHaveBeenCalledWith("SelectedContent", { type: "html" });
  });

  it("does not dispatch before Sigma reports the widget as ready", async () => {
    const failure = new Error("Sigma registration failed");
    const dispatch = vi.fn();
    const adapter = new ZohoWriterAdapter(
      vi.fn().mockRejectedValue(failure),
      () => ({ dispatch, request: vi.fn() }),
    );

    await expect(adapter.getSelectedHtml()).rejects.toThrow(failure);
    expect(dispatch).not.toHaveBeenCalled();
  });

  type Dispatch = (
    event: string,
    options: Record<string, unknown>,
  ) => Promise<unknown>;

  // Same control flow, milliseconds instead of seconds.
  const FAST = {
    changeWaitMs: 40,
    pollIntervalMs: 5,
    budgetMs: 400,
    documentReadTimeoutMs: 20,
    selectionReadTimeoutMs: 20,
  };

  const adapterWith = (dispatch: unknown, timings = FAST) =>
    new ZohoWriterAdapter(
      vi.fn().mockResolvedValue(undefined),
      () => ({
        dispatch: dispatch as Dispatch,
        request: vi.fn(),
      }),
      timings,
    );

  it("refuses to write when the selection is no longer the reviewed passage", async () => {
    const dispatch = vi.fn().mockResolvedValue("<p>something else</p>");
    const adapter = adapterWith(dispatch);

    await expect(
      adapter.replaceSelection("<p>new</p>", "<p>reviewed</p>"),
    ).rejects.toThrow(SelectionMovedError);

    // Only the verification read may have happened; no write was dispatched.
    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledWith("SelectedContent", { type: "html" });
  });

  // Simulates a Writer host: a document, a selection, and optionally one write
  // event that genuinely edits the document.
  const fakeHost = (options: {
    readsDocument: boolean;
    workingEvent?: string;
    clearsSelection?: boolean;
  }) => {
    const state = { doc: "<p>reviewed</p> tail", selection: "<p>reviewed</p>" };
    return vi.fn(async (event: string, payload: Record<string, unknown>) => {
      if (event === "SelectedContent") return state.selection;
      if (event === "DocumentContent") {
        if (!options.readsDocument) throw new Error("unsupported");
        return state.doc;
      }
      if (event === "GetDocumentContent" || event === "Content") {
        throw new Error("unsupported");
      }
      if (event === options.workingEvent) {
        const content = (payload.content ?? payload.html) as string;
        state.doc = `${content} tail`;
        state.selection = content;
        return undefined;
      }
      if (options.clearsSelection) {
        // Accepted, selection collapsed, document untouched: the exact shape
        // that previously produced a false success.
        state.selection = "";
        return undefined;
      }
      throw new Error(`${event} unsupported`);
    });
  };

  it("confirms an apply against the document, not the selection", async () => {
    const dispatch = fakeHost({
      readsDocument: true,
      workingEvent: "SetSelectedContent",
    });
    const adapter = adapterWith(dispatch);

    await expect(
      adapter.replaceSelection("<p>new</p>", "<p>reviewed</p>"),
    ).resolves.toEqual({ event: "SetSelectedContent", outcome: "applied" });
  });

  it("does not call a cleared selection a success when the document is unchanged", async () => {
    // The regression that mattered: SetSelectedContent collapsed the selection
    // without editing the document, and an empty read was mistaken for a change.
    const dispatch = fakeHost({ readsDocument: true, clearsSelection: true });
    const adapter = adapterWith(dispatch);

    // What matters is that the untouched document is never reported as applied.
    // Writer applies edits late and never confirms, so the honest verdict for
    // "no change observed yet" is unverified, not success and not failure.
    await expect(
      adapter.replaceSelection("<p>new</p>", "<p>reviewed</p>"),
    ).resolves.toMatchObject({ outcome: "unverified" });
  });

  it("reports unverified when the host hides the document and clears the selection", async () => {
    const dispatch = fakeHost({ readsDocument: false, clearsSelection: true });
    const adapter = adapterWith(dispatch);

    // Without a document to compare, success cannot be claimed either way.
    await expect(
      adapter.replaceSelection("<p>new</p>", "<p>reviewed</p>"),
    ).resolves.toMatchObject({ outcome: "unverified" });
  });

  it("dispatches exactly one write, so a late-landing edit cannot be duplicated", async () => {
    const dispatch = fakeHost({
      readsDocument: true,
      workingEvent: "SetSelectedContent",
    });
    const adapter = adapterWith(dispatch);

    await adapter.replaceSelection("<p>new</p>", "<p>reviewed</p>");

    const writes = dispatch.mock.calls.filter(
      ([event]) =>
        event !== "SelectedContent" && !DOCUMENT_READS.includes(event as string),
    );
    expect(writes).toEqual([
      ["SetSelectedContent", { type: "html", content: "<p>new</p>" }],
    ]);
  });

  it("reports every rejected event when the host accepts none", async () => {
    const dispatch = vi.fn(async (event: string) => {
      if (event === "SelectedContent") return "<p>reviewed</p>";
      throw new Error(`${event} unsupported`);
    });
    const adapter = adapterWith(dispatch);

    // The message must name what was attempted, so a failure is diagnosable.
    await expect(
      adapter.replaceSelection("<p>new</p>", "<p>reviewed</p>"),
    ).rejects.toThrow(/SetSelectedContent/);
  });

  it("does not freeze when the host stops answering selection reads mid-apply", async () => {
    // This froze the apply: the poll loop awaited SelectedContent with no
    // timeout, so the budget could never be reached from inside it.
    let writeSeen = false;
    const dispatch = vi.fn(async (event: string) => {
      if (event === "SelectedContent") {
        if (writeSeen) return new Promise<never>(() => {});
        return "<p>reviewed</p>";
      }
      if (DOCUMENT_READS.includes(event)) throw new Error("unsupported");
      writeSeen = true;
      return new Promise<never>(() => {});
    });
    const adapter = adapterWith(dispatch);

    // It must settle rather than hang, and an unanswerable read is honestly
    // "unverified" — indistinguishable from a cleared selection, never "applied".
    const result = await adapter.replaceSelection(
      "<p>new</p>",
      "<p>reviewed</p>",
    );
    expect(result.outcome).toBe("unverified");
  });

  it("stops at the overall budget instead of spinning forever", async () => {
    // A host that answers the first selection read and then nothing at all.
    // Before the budget existed this ran for minutes behind a spinner.
    let reads = 0;
    const dispatch = vi.fn(async (event: string) => {
      if (event === "SelectedContent" && reads++ === 0) return "<p>reviewed</p>";
      return new Promise<never>(() => {});
    });
    const adapter = adapterWith(dispatch, {
      changeWaitMs: 200,
      pollIntervalMs: 10,
      budgetMs: 80,
      documentReadTimeoutMs: 10,
      selectionReadTimeoutMs: 10,
    });

    const started = Date.now();
    await expect(
      adapter.replaceSelection("<p>new</p>", "<p>reviewed</p>"),
    ).resolves.toMatchObject({ outcome: "unverified" });
    // Bounded by the budget, not by the host deciding to answer.
    expect(Date.now() - started).toBeLessThan(1500);
  });

  it("probes the document reader once, not after every write attempt", async () => {
    vi.useFakeTimers();
    try {
      const dispatch = vi.fn(async (event: string) => {
        if (event === "SelectedContent") return "<p>reviewed</p>";
        if (DOCUMENT_READS.includes(event)) throw new Error("unsupported");
        return new Promise<never>(() => {});
      });
      const adapter = adapterWith(dispatch);

      const pending = adapter
        .replaceSelection("<p>new</p>", "<p>reviewed</p>")
        .catch(() => undefined);
      await vi.advanceTimersByTimeAsync(120_000);
      await pending;

      // Three reader candidates, attempted once between them — never again.
      const readCalls = dispatch.mock.calls.filter(([event]) =>
        DOCUMENT_READS.includes(event as string),
      );
      expect(readCalls).toHaveLength(DOCUMENT_READS.length);
    } finally {
      vi.useRealTimers();
    }
  });

  it("detects a write the host performs without ever settling the dispatch", async () => {
    // This is the live behaviour: Writer edits the document and leaves the
    // promise pending forever. Awaiting it reported failure on a real success.
    const state = { doc: "<p>reviewed</p>", selection: "<p>reviewed</p>" };
    const dispatch = vi.fn(async (event: string, payload: Record<string, unknown>) => {
      if (event === "SelectedContent") return state.selection;
      if (event === "DocumentContent") return state.doc;
      if (DOCUMENT_READS.includes(event)) throw new Error("unsupported");
      if (event === "SetSelectedContent") {
        // Applied a little later than the first poll, and never acknowledged.
        globalThis.setTimeout(() => {
          state.doc = payload.content as string;
        }, 15);
        return new Promise<never>(() => {});
      }
      return new Promise<never>(() => {});
    });
    const adapter = adapterWith(dispatch);

    await expect(
      adapter.replaceSelection("<p>new</p>", "<p>reviewed</p>"),
    ).resolves.toEqual({ event: "SetSelectedContent", outcome: "applied" });
  });
});
