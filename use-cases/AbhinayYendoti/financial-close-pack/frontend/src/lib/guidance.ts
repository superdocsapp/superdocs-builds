import type { ReadinessView } from "./readiness";
import type { CloseDetail } from "./types";

/**
 * Turns the server's readiness gate into directed guidance.
 *
 * The backend already computes everything needed to tell a controller what to do next —
 * `blockers` is an ordered list of plain-English problems and `ready_for_generation` says
 * whether the pack can be built. Neither was ever surfaced next to the control it governs,
 * so the only way to discover what was blocking a close was to attempt the close and be
 * rejected. This module maps each blocker onto the tab that fixes it, so every blocker can
 * be rendered as a link and every disabled button can explain itself.
 */

export type WorkspaceTab = "overview" | "documents" | "checklist" | "review" | "signoffs" | "pack";

export type Blocker = {
  /** The server's own wording, kept verbatim so there is one source of truth. */
  text: string;
  /** Where the user goes to resolve it. */
  tab: WorkspaceTab;
  /** Label for the link that takes them there. */
  action: string;
};

/**
 * Blocker text -> the tab that resolves it.
 *
 * Matched on a stable fragment rather than the whole string because the server
 * interpolates counts and pluralises. Order matters: the first match wins, so
 * "required document" is tested before the looser "document".
 */
const BLOCKER_ROUTES: Array<{ match: RegExp; tab: WorkspaceTab; action: string }> = [
  { match: /required document/i, tab: "documents", action: "Go to Documents" },
  { match: /awaiting classification/i, tab: "documents", action: "Classify documents" },
  { match: /checklist item/i, tab: "checklist", action: "Go to Checklist" },
  { match: /not generated/i, tab: "overview", action: "Generate the pack" },
  { match: /review decision/i, tab: "review", action: "Go to Review" },
  { match: /sign-off/i, tab: "signoffs", action: "Go to Sign-offs" },
  { match: /export pending/i, tab: "pack", action: "Go to Final Pack" }
];

export function routeBlocker(text: string): Blocker {
  const route = BLOCKER_ROUTES.find((candidate) => candidate.match.test(text));
  return {
    // The server pluralises "documents needs attention"; fix the agreement on the way out.
    text: text.replace(/documents needs/i, "documents need"),
    tab: route?.tab ?? "overview",
    action: route?.action ?? "Review"
  };
}

export function routeBlockers(blockers: string[]): Blocker[] {
  return blockers.map(routeBlocker);
}

export type StepState = "done" | "current" | "todo";

export type Step = {
  tab: WorkspaceTab;
  label: string;
  /** Shown under the label when this is the step the user should be on. */
  hint: string;
  state: StepState;
  /** "3 of 7 done" style progress, or null where the step has no countable parts. */
  progress: string | null;
};

/**
 * The close, expressed as the ordered sequence a controller actually works through.
 *
 * The order is the one the backend enforces — documents and checklist gate generation,
 * generation gates review, and every dimension gates the close — but it was previously
 * only written down for engineers, in a README table and a comment above CONTRACT_LABELS.
 */
export function computeSteps(readiness: ReadinessView, closed: boolean): Step[] {
  const docsDone = readiness.docsRequired > 0 && readiness.docsReady >= readiness.docsRequired;
  const checklistDone = readiness.checklistDone >= readiness.checklistRequired;
  const reviewsDone = readiness.reviewsTotal > 0 && readiness.reviewsResolved >= readiness.reviewsTotal;
  const signoffsDone = readiness.signoffsDone >= readiness.signoffsRequired;

  const raw: Array<Omit<Step, "state">> = [
    {
      tab: "documents",
      label: "Collect documents",
      hint: "Upload each required schedule and tell us what it is.",
      progress: `${readiness.docsReady} of ${readiness.docsRequired} ready`
    },
    {
      tab: "checklist",
      label: "Work the checklist",
      hint: "Tick off each control once you have the evidence for it.",
      progress: `${readiness.checklistDone} of ${readiness.checklistRequired} done`
    },
    {
      tab: "overview",
      label: "Build the pack",
      hint: "We draft the close pack from the evidence you collected.",
      progress: readiness.generated ? "Drafted" : "Not started"
    },
    {
      tab: "review",
      label: "Review changes",
      hint: "Approve or reject each proposed change before it reaches the pack.",
      progress: readiness.reviewsTotal ? `${readiness.reviewsResolved} of ${readiness.reviewsTotal} decided` : null
    },
    {
      tab: "signoffs",
      label: "Collect sign-offs",
      hint: "Each reviewer approves in their own name.",
      progress: `${readiness.signoffsDone} of ${readiness.signoffsRequired} signed`
    },
    {
      tab: "pack",
      label: "Export and close",
      hint: "Produce the final pack, then lock the period.",
      progress: readiness.exported ? "Exported" : "Not exported"
    }
  ];

  const done = [docsDone, checklistDone, readiness.generated, reviewsDone, signoffsDone, readiness.exported];
  // The first unfinished step is the one to work on; everything after it is simply "todo"
  // rather than locked, because a controller may legitimately look ahead.
  const currentIndex = done.findIndex((finished) => !finished);

  return raw.map((step, index) => ({
    ...step,
    state: closed || done[index] ? "done" : index === currentIndex ? "current" : "todo"
  }));
}

/** The single sentence shown at the top of the workspace: what to do right now. */
export function nextAction(
  readiness: ReadinessView,
  closed: boolean
): { headline: string; detail: string; tab: WorkspaceTab; action: string } | null {
  if (closed) return null;
  if (readiness.canClose) {
    return {
      headline: "Everything is ready — you can close this period.",
      detail: "All evidence is collected, every change is decided, and the pack is exported.",
      tab: "pack",
      action: "Close the period"
    };
  }
  const first = readiness.blockers[0];
  if (!first) return null;
  const blocker = routeBlocker(first);
  const remaining = readiness.blockers.length - 1;
  return {
    headline: blocker.text,
    detail: remaining > 0 ? `${remaining} more item${remaining === 1 ? "" : "s"} after this one.` : "This is the last item.",
    tab: blocker.tab,
    action: blocker.action
  };
}

/** Why "Generate" cannot run yet, phrased for the person looking at the button. */
export function generationBlockReason(readiness: ReadinessView): string | null {
  if (readiness.canGenerate) return null;
  const relevant = readiness.blockers
    .map(routeBlocker)
    .filter((blocker) => blocker.tab === "documents" || blocker.tab === "checklist");
  if (!relevant.length) return "Finish collecting documents and the checklist first.";
  return `${relevant.map((blocker) => blocker.text).join(", ")}.`;
}

/**
 * Document types the close still needs, as readable names.
 *
 * `required_document_types` and `readiness.documents.missing_types` were both fetched and
 * never rendered, so the empty Documents tab never said what to upload.
 */
export function missingDocumentTypes(close: CloseDetail | null): string[] {
  return close?.readiness?.documents?.missing_types ?? [];
}

/** Turn a backend enum like `AP_RECONCILIATION` into `AP reconciliation`. */
export function humanizeType(value: string): string {
  const spaced = value.replace(/_/g, " ").toLowerCase().trim();
  if (!spaced) return value;
  // Keep short finance initialisms upper-cased; they read wrong in sentence case.
  return spaced
    .split(" ")
    .map((word, index) =>
      ["ap", "ar", "gl", "vat", "gst", "fx"].includes(word)
        ? word.toUpperCase()
        : index === 0
          ? word.charAt(0).toUpperCase() + word.slice(1)
          : word
    )
    .join(" ");
}
