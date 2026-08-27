/**
 * The fake this page is tested against streams real repairs.
 *
 * Every line it sends was produced by the engine and recorded by
 * tests/test_frontend_fixtures.py, which fails if the recording drifts. A page
 * that tells somebody what happened to their document must be tested against
 * what actually happens to documents.
 */
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import healthy from "./fixtures/healthy.json";
import truncated from "./fixtures/truncated.json";
import missingContentTypes from "./fixtures/missing-content-types.json";
import unclosedTags from "./fixtures/unclosed-tags.json";
import badCharacters from "./fixtures/bad-characters.json";
import missingDocumentPart from "./fixtures/missing-document-part.json";
import notAWordFile from "./fixtures/not-a-word-file.json";
import emptyBody from "./fixtures/empty-body.json";
import illustrated from "./fixtures/illustrated.json";
import truncatedIllustrated from "./fixtures/truncated-illustrated.json";

export interface Capture {
  name: string;
  filename: string;
  events: { stage: string; message: string }[];
  report: Record<string, unknown>;
}

export const CAPTURES: Capture[] = [
  healthy,
  truncated,
  missingContentTypes,
  unclosedTags,
  badCharacters,
  missingDocumentPart,
  notAWordFile,
  emptyBody,
  illustrated,
  truncatedIllustrated,
] as Capture[];

let serving: Capture = truncated as Capture;
export function serve(name: string) {
  const found = CAPTURES.find((c) => c.name === name);
  if (!found) throw new Error(`no captured repair called ${name}`);
  serving = found;
}

/** Cut the stream off after `n` lines, the way a dropped connection does. */
let cutAfter: number | null = null;
export function dropConnectionAfter(n: number | null) {
  cutAfter = n;
}

/** What this copy of the page can do. The default is off, because the offline
 *  rebuild is the product and styling is the extra. */
let styling: { on: boolean; note: string } = { on: false, note: "" };
export function serveCapabilities(on: boolean, note = "") {
  styling = { on, note };
}

/** How the styling endpoint answers next. Stages first, then the final line —
 *  the same wire shape as a repair, because it is the same situation. */
let stylingAnswer: {
  status: number;
  detail?: string;
  stages: string[];
  final: Record<string, unknown>;
} = {
  status: 200,
  stages: ["Sending the recovered content to SuperDocs for styling…"],
  final: {
    ok: true,
    notes: ["SuperDocs returned a styled file."],
    filename: "d-repaired-styled.docx",
    download: "/api/download/styled-token",
    ops_confirmed: false,
    warnings: 0,
  },
};
export function serveStyling(next: Partial<typeof stylingAnswer>) {
  stylingAnswer = { ...stylingAnswer, ...next };
}

/** Overrides layered onto the served capture's own styling-outcome fields in
 *  the final `/api/recover` event -- B3 moved styling inside the recovery, so
 *  this is where its outcome now varies, the same job `serveStyling` did for
 *  the old standalone endpoint. Only these fields are touched; everything
 *  else in the capture's `report` (verdict, counts, preview) still comes from
 *  the fixture untouched, per B26. `null` clears the override. */
let stylingOutcome: Partial<{
  styled: boolean;
  styling_note: string;
  styling_rejected: boolean;
  download: string | null;
  plain_download: string | null;
}> | null = null;
export function serveStylingOutcome(
  o: Partial<{
    styled: boolean;
    styling_note: string;
    styling_rejected: boolean;
    download: string | null;
    plain_download: string | null;
  }> | null,
): void {
  stylingOutcome = o;
}

/** The actual wire shape `readStream` (lib/repair.ts) parses: `data: {json}`
 *  lines, each terminated by a blank line. A single trailing "\n" per line
 *  (what this used to send) never produces the "\n\n" `readStream` splits on,
 *  so nothing was ever read from it -- every repair in this suite failed with
 *  "the connection dropped" regardless of what the fixture said. */
function sse(lines: string[]) {
  const body = new ReadableStream({
    start(controller) {
      const encoder = new TextEncoder();
      const limit = cutAfter ?? lines.length;
      lines.slice(0, limit).forEach((l) => controller.enqueue(encoder.encode(`data: ${l}\n\n`)));
      controller.close();
    },
  });
  return new HttpResponse(body, { headers: { "content-type": "text/event-stream" } });
}

/** State for the counter's five endpoints (PRD §12 / Task 3), kept the same
 *  way `serving`/`stylingAnswer` already are: one mutable object a test bends
 *  before acting, reset between tests. */
let counter: {
  turnsLeft: number;
  turnsCap: number;
  retentionSeconds: number;
  receipts: Record<string, unknown>[];
  download: string;
  plainDownload: string;
  authoredWords: number;
  /** The current sheet -- "" means no accepted turn has changed the document
   *  yet, so the client should show `report.preview_html` instead. */
  previewHtml: string;
  /** What `previewHtml` was before each applied turn, so a revert can hand
   *  the sheet back exactly what was on screen before that turn landed. */
  previewStack: string[];
} = {
  turnsLeft: 10,
  turnsCap: 10,
  retentionSeconds: 1800,
  receipts: [],
  download: "/api/download/truncated-token",
  plainDownload: "/api/download/truncated-token",
  authoredWords: 0,
  previewHtml: "",
  previewStack: [],
};
export function resetCounter(next: Partial<typeof counter> = {}) {
  counter = {
    turnsLeft: 10,
    turnsCap: 10,
    retentionSeconds: 1800,
    receipts: [],
    download: "/api/download/truncated-token",
    plainDownload: "/api/download/truncated-token",
    authoredWords: 0,
    previewHtml: "",
    previewStack: [],
    ...next,
  };
}

/** How the *next* turn answers: whether it applied, what it cost, and the
 *  note that becomes both the ledger line and the "said" sentence. Queued
 *  rather than fixed, because the scenario this feature exists to get right —
 *  two kinds of no — needs consecutive turns that read differently. */
let nextTurn: {
  stages: string[];
  applied: boolean;
  note: string;
  previewHtml?: string;
} = {
  stages: ["Sending your change to SuperDocs…"],
  applied: true,
  note: "Done.",
};
export function serveTurn(next: Partial<typeof nextTurn>) {
  nextTurn = { ...nextTurn, ...next };
}

/** Holds the next `/turn` response open until released -- so a test can
 *  observe the field disabled mid-flight instead of racing a mock that
 *  otherwise answers within a tick. */
let turnGate: Promise<void> | null = null;
let releaseGate: (() => void) | null = null;
export function holdNextTurn() {
  turnGate = new Promise((resolve) => {
    releaseGate = resolve;
  });
}
export function releaseNextTurn() {
  releaseGate?.();
  turnGate = null;
  releaseGate = null;
}

export const handlers = [
  http.get("/api/capabilities", () =>
    HttpResponse.json({ styling: styling.on, note: styling.note }),
  ),

  http.post("/api/style/:token", () => {
    if (stylingAnswer.status !== 200) {
      return HttpResponse.json({ detail: stylingAnswer.detail }, { status: stylingAnswer.status });
    }
    return sse([
      ...stylingAnswer.stages.map((m) => JSON.stringify({ stage: "superdocs", message: m })),
      JSON.stringify({ done: true, ...stylingAnswer.final }),
    ]);
  }),

  http.post("/api/recover", () => {
    const capture = serving;
    const report = stylingOutcome ? { ...capture.report, ...stylingOutcome } : capture.report;
    return sse([
      ...capture.events.map((e) => JSON.stringify(e)),
      JSON.stringify({ done: true, ...report }),
    ]);
  }),

  http.post("/api/style/:token/open", () =>
    HttpResponse.json({
      session: "test-session",
      turns_left: counter.turnsLeft,
      turns_cap: counter.turnsCap,
      retention_seconds: counter.retentionSeconds,
      receipts: counter.receipts,
    }),
  ),

  http.post("/api/style/:token/turn", async ({ request }) => {
    const body = (await request.json()) as { message: string };
    if (turnGate) await turnGate;
    const turn = nextTurn;
    counter.turnsLeft = Math.max(0, counter.turnsLeft - 1);
    const receipt = {
      asked: body.message,
      note: turn.note,
      turn_index: counter.receipts.length + 1,
      applied: turn.applied,
      supplied: null,
    };
    counter.receipts = [...counter.receipts, receipt];
    if (turn.applied) {
      counter.download = `/api/download/truncated-token-v${counter.receipts.length}`;
      // Only an applied turn moves the sheet -- a refusal changes nothing,
      // so it pushes no new preview and the stack it could be reverted onto
      // stays untouched.
      counter.previewStack.push(counter.previewHtml);
      counter.previewHtml = turn.previewHtml ?? "";
    }
    const final: Record<string, unknown> = {
      done: true,
      applied: turn.applied,
      note: turn.note,
      turns_left: counter.turnsLeft,
      turns_cap: counter.turnsCap,
      receipts: counter.receipts,
      download: counter.download,
      plain_download: counter.plainDownload,
      authored_words: counter.authoredWords,
      preview_html: turn.applied ? counter.previewHtml : "",
    };
    return sse([
      ...turn.stages.map((m) => JSON.stringify({ stage: "superdocs", message: m })),
      JSON.stringify(final),
    ]);
  }),

  http.post("/api/style/:token/revert", () => {
    const popped = counter.receipts[counter.receipts.length - 1] as
      | { asked?: string }
      | undefined;
    counter.receipts = counter.receipts.slice(0, -1);
    // Hand the sheet back exactly what it showed before the reverted turn --
    // "" once the stack is exhausted, meaning back to the original rebuild.
    counter.previewHtml = counter.previewStack.pop() ?? "";
    return HttpResponse.json({
      note: "That change was put back.",
      compose_text: popped?.asked ?? "",
      session: "test-session",
      turns_left: counter.turnsLeft,
      turns_cap: counter.turnsCap,
      retention_seconds: counter.retentionSeconds,
      receipts: counter.receipts,
      preview_html: counter.previewHtml,
    });
  }),

  http.get("/api/style/:token/session", () =>
    HttpResponse.json({
      turns_left: counter.turnsLeft,
      turns_cap: counter.turnsCap,
      receipts: counter.receipts,
      download: counter.download,
      plain_download: counter.plainDownload,
      authored_words: counter.authoredWords,
      preview_html: counter.previewHtml,
    }),
  ),

  http.delete("/api/style/:token/session", () => HttpResponse.json({ disposed: true })),
];

export const server = setupServer(...handlers);
