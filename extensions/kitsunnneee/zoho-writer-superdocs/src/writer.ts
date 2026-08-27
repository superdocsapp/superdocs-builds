import type { HostWriteOutcome, HostWriteResult, WriterPort } from "./types";
import {
  getSigmaWriterClient,
  initializeSigma,
  type SigmaWriterClient,
} from "./api";
import { normalizeSelectedHtml } from "./normalizers";

// Raised when the document moved under us between review and apply. Writing then
// would edit a passage nobody reviewed, so it is refused instead.
export class SelectionMovedError extends Error {
  constructor() {
    super(
      "The Writer selection is no longer the passage that was reviewed, so nothing was written." +
        " Re-select the original passage, or run a new review.",
    );
    this.name = "SelectionMovedError";
  }
}

// The read side is dispatch("SelectedContent", …). The write side is not
// published, but this workspace showed SetSelectedContent with {type,content}
// genuinely rewriting the paragraph, so that single shape is what gets sent.
//
// Earlier this tried five events across four payload shapes. That was wrong:
// each attempt can land seconds after it was written off, so a "failed" shape
// followed by another attempt risks writing the text twice into the document.
// One shape, observed patiently, cannot duplicate anything.
const WRITE_EVENT = "SetSelectedContent";

const buildWritePayload = (html: string): Record<string, unknown> => ({
  type: "html",
  content: html,
});

// Reading the whole document is the only trustworthy witness to a write: the
// selection collapses on some events, and an empty selection is not evidence.
const DOCUMENT_READ_EVENTS: readonly string[] = [
  "DocumentContent",
  "GetDocumentContent",
  "Content",
];

// An unsupported event name is not rejected by the host — the promise simply
// never settles. Without this the apply hangs indefinitely.
const DOCUMENT_READ_TIMEOUT_MS = 2500;
const SELECTION_READ_TIMEOUT_MS = 2500;

// Writer performs the edit but never settles the dispatch promise, so waiting on
// it proves nothing. The document is polled instead. Observed behaviour is that
// the edit lands within a couple of hundred milliseconds — the earlier multi-shot
// retry loop was the actual source of slowness, not Writer. A short, tight poll
// keeps genuine verification while feeling instant in the normal case.
const CHANGE_POLL_INTERVAL_MS = 120;
const CHANGE_WAIT_MS = 1_800;

// Hard ceiling, so an unresponsive host cannot leave a spinner running forever.
const APPLY_BUDGET_MS = 1_800;

const sleep = (ms: number) =>
  new Promise<void>((resolve) => globalThis.setTimeout(resolve, ms));

// Probed once per page session: the event that reads the document, or null when
// the host exposes none. Re-probing after every write is what blew the budget.
let documentReadEvent: string | null | undefined;

// The probe result is page-session state; tests must not inherit it.
export const resetHostCapabilityProbe = (): void => {
  documentReadEvent = undefined;
};

const TIMED_OUT = Symbol("timed out");

const withTimeout = async <T>(
  work: Promise<T>,
  timeoutMs: number,
): Promise<T | typeof TIMED_OUT> => {
  let timer: ReturnType<typeof globalThis.setTimeout> | undefined;
  try {
    return await Promise.race([
      work,
      new Promise<typeof TIMED_OUT>((resolve) => {
        timer = globalThis.setTimeout(() => resolve(TIMED_OUT), timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== undefined) globalThis.clearTimeout(timer);
  }
};

export interface ApplyTimings {
  changeWaitMs: number;
  pollIntervalMs: number;
  budgetMs: number;
  documentReadTimeoutMs: number;
  selectionReadTimeoutMs: number;
}

const DEFAULT_TIMINGS: ApplyTimings = {
  changeWaitMs: CHANGE_WAIT_MS,
  pollIntervalMs: CHANGE_POLL_INTERVAL_MS,
  budgetMs: APPLY_BUDGET_MS,
  documentReadTimeoutMs: DOCUMENT_READ_TIMEOUT_MS,
  selectionReadTimeoutMs: SELECTION_READ_TIMEOUT_MS,
};

export class ZohoWriterAdapter implements WriterPort {
  constructor(
    private readonly initializer: () => Promise<void> = initializeSigma,
    private readonly client: () => SigmaWriterClient = getSigmaWriterClient,
    // Injectable so tests exercise the real control flow without real waits.
    private readonly timings: ApplyTimings = DEFAULT_TIMINGS,
  ) {}

  initialize(): Promise<void> {
    return this.initializer();
  }

  // Every host dispatch is bounded. Writer can leave a call pending forever, and
  // an unbounded await here froze the whole apply from inside its own budget.
  async getSelectedHtml(): Promise<string> {
    await this.initializer();
    const selected = await withTimeout(
      this.client().dispatch("SelectedContent", { type: "html" }),
      this.timings.selectionReadTimeoutMs,
    );
    if (selected === TIMED_OUT) {
      throw new Error(
        "Writer did not return the current selection. Click into the document, re-select the passage, and try again.",
      );
    }
    return normalizeSelectedHtml(selected);
  }

  // Poll-time variant: a read that cannot be answered is simply no evidence yet,
  // so it must not abort the observation loop.
  private async peekSelection(): Promise<string> {
    try {
      const selected = await withTimeout(
        this.client().dispatch("SelectedContent", { type: "html" }),
        this.timings.selectionReadTimeoutMs,
      );
      return selected === TIMED_OUT ? "" : normalizeSelectedHtml(selected);
    } catch {
      return "";
    }
  }

  // Writes the approved wording over the reviewed selection. Enabling Writer's
  // own Track Changes before calling this makes the result a native tracked
  // change, reviewable with Writer's accept/reject controls — the host's review
  // primitives are used rather than reimplemented.
  async replaceSelection(
    html: string,
    expectedHtml: string,
  ): Promise<HostWriteResult> {
    await this.initializer();

    // Guard first: never write without confirming the selection is still exactly
    // what was reviewed.
    const current = await this.getSelectedHtml();
    if (current !== expectedHtml) throw new SelectionMovedError();

    // Snapshot the document if the host will give it to us. With a snapshot the
    // verdict is definitive; without one it falls back to the selection, which
    // cannot distinguish "replaced" from "selection cleared".
    const documentBefore = await this.readDocument();

    const deadline = Date.now() + this.timings.budgetMs;
    let rejection: string | undefined;
    // Fire and observe. Writer performs the edit without ever settling this
    // promise, so its result proves nothing — only the document does.
    void Promise.resolve(
      this.client().dispatch(WRITE_EVENT, buildWritePayload(html)),
    ).catch((error: unknown) => {
      rejection = error instanceof Error ? error.message : "rejected";
    });

    const observed = await this.waitForChange(
      documentBefore,
      expectedHtml,
      deadline,
    );
    if (observed !== "none") return { event: WRITE_EVENT, outcome: observed };

    // Only an outright rejection is a failure. Writer routinely applies the
    // edit later than this window without ever confirming, so "not observed
    // yet" is reported as unverified rather than as an error.
    if (rejection) {
      throw new Error(
        `Writer rejected ${WRITE_EVENT} (${rejection}). Use the export instead.`,
      );
    }
    return { event: WRITE_EVENT, outcome: "unverified" };
  }

  // Polls until the edit shows up, because the host applies it asynchronously and
  // a single immediate read reports failure on a write that did land.
  private async waitForChange(
    documentBefore: string | undefined,
    expectedHtml: string,
    deadline: number,
  ): Promise<HostWriteOutcome | "none"> {
    const stopAt = Math.min(Date.now() + this.timings.changeWaitMs, deadline);
    let sawClearedSelection = false;

    while (true) {
      if (documentBefore !== undefined) {
        const now = await this.readDocument();
        if (now !== undefined && now !== documentBefore) return "applied";
      } else {
        const selection = await this.peekSelection();
        if (selection.trim().length === 0) sawClearedSelection = true;
        else if (selection !== expectedHtml) return "applied";
      }
      if (Date.now() >= stopAt) break;
      await sleep(this.timings.pollIntervalMs);
    }

    // A cleared selection with no readable document is not evidence either way.
    return sawClearedSelection && documentBefore === undefined
      ? "unverified"
      : "none";
  }

  private async readDocument(): Promise<string | undefined> {
    if (documentReadEvent === null) return undefined;

    const candidates =
      documentReadEvent === undefined
        ? DOCUMENT_READ_EVENTS
        : [documentReadEvent];

    for (const event of candidates) {
      try {
        const result = await withTimeout(
          this.client().dispatch(event, { type: "html" }),
          this.timings.documentReadTimeoutMs,
        );
        if (result === TIMED_OUT) continue;
        const html = normalizeSelectedHtml(result);
        if (html.length > 0) {
          documentReadEvent = event;
          return html;
        }
      } catch {
        continue;
      }
    }
    // Remember the absence so later verifications skip the probe entirely.
    if (documentReadEvent === undefined) documentReadEvent = null;
    return undefined;
  }
}
