/**
 * DEMO_NOW is the fixed reference clock for all seed data.
 *
 * Staleness, "recently changed," and dashboard aggregations are computed
 * relative to this constant rather than `Date.now()`. That keeps the demo
 * deterministic — evidence that is "stale" today stays stale next month,
 * and reviewers looking at the same document see the same risk score,
 * regardless of when the app happens to be opened. A production build would
 * replace this with the real clock (or a server-supplied "as of" time).
 */
export const DEMO_NOW = "2026-08-20T09:00:00.000Z";

/**
 * Live in-session actions (verifying a claim, approving a document, etc.)
 * need timestamps that sort after the seed data and after each other. Each
 * call advances the clock by a fixed step so a burst of actions in one demo
 * session still produces a sensible, strictly increasing timeline.
 */
let sessionTick = 0;
export function nextSessionTimestamp(): string {
  sessionTick += 1;
  const stepMs = sessionTick * 4 * 60 * 1000; // +4 minutes per action
  return new Date(new Date(DEMO_NOW).getTime() + stepMs).toISOString();
}

export const CURRENT_USER = "You";

/** Reference roster — kept as plain strings on records; listed here for consistency across seed files. */
export const PEOPLE = {
  priya: "Priya Nandakumar",
  darius: "Darius Cole",
  wenqing: "Wenqing Zhao",
  aaron: "Aaron Michaelson",
  lena: "Lena Forsythe",
  ravi: "Ravi Subramaniam",
  gabrielle: "Gabrielle Okafor",
  tomas: "Tomas Novak",
} as const;
