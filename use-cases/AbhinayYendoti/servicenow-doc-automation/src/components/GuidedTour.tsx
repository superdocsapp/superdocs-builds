import { useEffect, useLayoutEffect, useState } from "react";
import { ArrowRight, X } from "lucide-react";

/**
 * First-run walkthrough.
 *
 * The app is deliberately dense — a queue, a live agent feed, a verification
 * console, per-chunk decisions and an audit trail all at once. Density is
 * useful to someone who knows what they are looking at and hostile to someone
 * who does not, so the first visit gets walked through it once.
 *
 * Anchored to `data-tour` attributes so the copy cannot drift away from the
 * region it describes: a step whose anchor is not on screen is skipped rather
 * than pointing at nothing.
 */
const STORAGE_KEY = "serviceflow.tour.seen";

type TourStep = {
  anchor: string;
  title: string;
  body: string;
};

const TOUR: TourStep[] = [
  {
    anchor: "queue",
    title: "Start with a closed change",
    body: "This queue is read live from the ServiceNow Table API. Records flagged incomplete are rejected before anything is sent to SuperDocs — pick one and the whole run keys off it."
  },
  {
    anchor: "next",
    title: "There is always one next step",
    body: "Whatever else is on screen, this bar names the single thing to do now. It is computed by the server from the real state of the run, not from what the page happens to be showing."
  },
  {
    anchor: "feed",
    title: "Watch the model work",
    body: "SuperDocs streams its own progress. You see the sections it reads, the passages it rewrites, and each batch it puts up for review, as it happens."
  },
  {
    anchor: "verify",
    title: "ServiceNow stays authoritative",
    body: "Two values must survive character for character. Every proposed change is checked against them before you see it, and export is refused if the finished document drifts."
  },
  {
    anchor: "review",
    title: "Decide each change",
    body: "SuperDocs proposes chunk-level edits and waits. Anything that rewrites an owned value is blocked — the server refuses it even if the browser asks — so reject it, or have the section redone."
  },
  {
    anchor: "audit",
    title: "Everything is recorded",
    body: "Each step is appended to an audit trail, and the exported document is written back to the ServiceNow change with its checksum."
  }
];

export function GuidedTour({ onClose, force }: { onClose: () => void; force: boolean }) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);

  const visible = TOUR.filter((step) => document.querySelector(`[data-tour="${step.anchor}"]`));
  const step = visible[index];

  useLayoutEffect(() => {
    if (!step) return;

    const element = document.querySelector(`[data-tour="${step.anchor}"]`);
    if (!element) return;

    element.scrollIntoView({ behavior: "smooth", block: "center" });

    // The scroll is animated, so the rect is measured after it settles.
    const timer = window.setTimeout(() => setRect(element.getBoundingClientRect()), 320);
    return () => window.clearTimeout(timer);
  }, [step]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") finish();
      if (event.key === "ArrowRight" || event.key === "Enter") advance();
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  function finish() {
    try {
      window.localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      /* private windows and blocked site data are fine; the tour just repeats */
    }
    onClose();
  }

  function advance() {
    if (index + 1 >= visible.length) finish();
    else setIndex(index + 1);
  }

  if (!step) return null;

  const style = rect
    ? {
        top: Math.min(window.innerHeight - 220, Math.max(16, rect.top)),
        left: Math.min(window.innerWidth - 380, Math.max(16, rect.right + 16))
      }
    : { top: 120, left: 120 };

  return (
    <div className="tour-layer" role="dialog" aria-label="Guided tour">
      <div className="tour-scrim" onClick={finish} />

      {rect && (
        <div
          aria-hidden="true"
          className="tour-ring"
          style={{
            top: rect.top - 6,
            left: rect.left - 6,
            width: rect.width + 12,
            height: rect.height + 12
          }}
        />
      )}

      <article className="tour-card" style={style}>
        <header>
          <span className="eyebrow">
            {index + 1} of {visible.length}
          </span>
          <button aria-label="Close tour" className="icon-button" onClick={finish} type="button">
            <X size={14} />
          </button>
        </header>

        <strong>{step.title}</strong>
        <p>{step.body}</p>

        <div className="tour-actions">
          <button className="ghost-button" onClick={finish} type="button">
            Skip
          </button>
          <button className="primary-button" onClick={advance} type="button">
            {index + 1 >= visible.length ? "Got it" : "Next"}
            <ArrowRight size={14} />
          </button>
        </div>
      </article>

      {force && <span className="sr-only">Guided tour reopened</span>}
    </div>
  );
}

/** Whether the walkthrough has already been seen on this browser. */
export function tourAlreadySeen() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}
