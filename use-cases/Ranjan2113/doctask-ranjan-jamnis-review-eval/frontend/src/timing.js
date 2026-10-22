/**
 * Timing primitives, kept free of React so they can be tested with
 * `node --test` and no browser.
 *
 * This is the measurement instrument for the whole study. Decision time is one
 * of the three things we claim to measure, so the rules are explicit:
 *
 *  - Three moments are recorded per change: `shownAt` (rendered), `engagedAt`
 *    (the reviewer first actually reached it) and `decidedAt` (the click).
 *  - **Decision time is measured from engagement, not from render.** In the
 *    batch conditions every change renders at once, so render-to-click for the
 *    fifth change includes all the time spent on the first four. Pilot run 1
 *    measured it that way and produced a fictitious 40x gap between batch
 *    (~75s) and sequential (~2s) conditions: the batch numbers climbed
 *    monotonically in click order because they were one clock read seven
 *    times, not seven measurements. See PROGRESS.md A18.
 *  - Render-to-click is still kept as `renderToDecisionMs`. It is the right
 *    measure for a different question -- how long a whole batch takes -- and
 *    discarding it would hide the artefact rather than correct it.
 *  - In the sequential conditions engagement and render coincide, so the two
 *    numbers agree there. That is the check that the fix is sound.
 *  - It stops on the decision click. A reviewer who revisits a change starts a
 *    fresh interval; both are recorded, and analysis decides what to do with a
 *    revision rather than the UI silently overwriting one.
 *  - Wall-clock ISO timestamps go to the server, which recomputes the
 *    duration. The client's own elapsed number is for display only. Two
 *    independent clocks disagreeing is a bug we want visible, not averaged.
 */

/** Monotonic milliseconds. Immune to the system clock being adjusted mid-session. */
export function monotonicNow() {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
    return performance.now();
  }
  return Date.now();
}

export function isoNow() {
  return new Date().toISOString();
}

/**
 * Tracks one open timing interval per change id.
 *
 * Deliberately not a React hook so its behaviour is testable directly.
 * useDecisionTimer wraps it.
 */
export class DecisionClock {
  constructor({ now = monotonicNow, iso = isoNow } = {}) {
    this.now = now;
    this.iso = iso;
    this.open = new Map();
  }

  /**
   * Begin timing a change. Calling start twice for the same id without an
   * intervening stop keeps the ORIGINAL start: a re-render must not reset the
   * clock, or every measured time would collapse toward zero on any state
   * change.
   */
  start(changeId) {
    if (this.open.has(changeId)) return this.open.get(changeId);
    const entry = {
      shownAt: this.iso(),
      renderedAt: this.now(),
      engagedAt: null,
      engagedIso: null,
    };
    this.open.set(changeId, entry);
    return entry;
  }

  /**
   * Mark the moment the reviewer actually reached this change -- scrolled it
   * into view, hovered it, or focused it.
   *
   * Idempotent: only the FIRST engagement counts. Later hovers while thinking
   * must not restart the clock, or long deliberation would read as fast.
   * A change decided without any engagement signal falls back to its render
   * time, so a decision can never be recorded with no interval at all.
   */
  engage(changeId) {
    const entry = this.open.get(changeId);
    if (!entry || entry.engagedAt !== null) return entry || null;
    entry.engagedAt = this.now();
    entry.engagedIso = this.iso();
    return entry;
  }

  isEngaged(changeId) {
    const entry = this.open.get(changeId);
    return Boolean(entry && entry.engagedAt !== null);
  }

  /** Force a fresh interval, e.g. when a change is genuinely re-shown. */
  restart(changeId) {
    this.open.delete(changeId);
    return this.start(changeId);
  }

  isOpen(changeId) {
    return this.open.has(changeId);
  }

  elapsed(changeId) {
    const entry = this.open.get(changeId);
    if (!entry) return 0;
    return this.now() - (entry.engagedAt ?? entry.renderedAt);
  }

  /**
   * Close the interval and return what the server needs.
   * Returns null when the change was never started -- the caller must not
   * invent a start time for it.
   */
  stop(changeId) {
    const entry = this.open.get(changeId);
    if (!entry) return null;
    this.open.delete(changeId);

    const decidedAt = this.iso();
    const nowMs = this.now();
    const engagedAt = entry.engagedAt ?? entry.renderedAt;

    return {
      shownAt: entry.shownAt,
      // Falls back to render when nothing ever engaged, so the server always
      // receives a usable interval.
      engagedAt: entry.engagedIso ?? entry.shownAt,
      decidedAt,
      elapsedMs: Math.round(nowMs - engagedAt),
      renderToDecisionMs: Math.round(nowMs - entry.renderedAt),
      wasEngaged: entry.engagedAt !== null,
    };
  }

  reset() {
    this.open.clear();
  }
}
