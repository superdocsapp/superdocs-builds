/** The pane's state as a reducer, so the behaviour tests without Word.
 *
 * Four rules the reviewer asked for:
 *  1. Newest scan on top — a finding from the sentence just typed appears above
 *     the ones already answered.
 *  2. Document order within a scan.
 *  3. Typing re-arms the scan — a changed document means the current scan is
 *     stale and the button returns.
 *  4. Answered rows stay — a redacted item greys out and keeps its place.
 *
 * Nothing here removes anything: `confirm` marks a row, the caller applies it
 * through the host.
 *
 * See extensions/redaction-pane/README.md § "Undo".
 */

/** No "confirmed": the pane calls Word and records the result in one action, so
 * nothing ever sat between pending and applied. */
export type Status = "pending" | "applied" | "dismissed" | "failed";

export interface Candidate {
  id: string;
  key: string;
  category: "personal" | "health" | "account" | "privileged";
  kind: string;
  detector: "pattern" | "ner" | "llm";
  text: string;
  sentence: string;
  part_type: string;
  chunk_id: string;
  char_start: number;
  char_end: number;
  /** What Word writes in its place: `[CREDIT CARD REDACTED]`. Computed once by
   * the service so pane, document and log agree on what was left behind. */
  marker: string;
  status: Status;
  /** Which scan produced it. The list sorts on this descending, which is what
   * puts the newest batch on top. */
  batch: number;
  note?: string;
}

export interface State {
  candidates: Candidate[];
  batch: number;
  scanning: boolean;
  /** True when the document changed after the last scan. Drives both the
   * button label and the banner. */
  stale: boolean;
  scanned: boolean;
  /** Ids added by the most recent scan — the pane scrolls to the first of
   * these, which is the "scroll moves up automatically" behaviour. */
  newest: string[];
  error?: string;
}

export const initial: State = {
  candidates: [],
  batch: 0,
  scanning: false,
  stale: false,
  scanned: false,
  newest: [],
};

/** A candidate as the service sends it. `status` is optional but not decoration:
 * the service returns every candidate, decided ones included, so a reloaded pane
 * shows a reviewer's work. Defaulting to "pending" would erase it. */
export type Incoming = Omit<Candidate, "status" | "batch"> & { status?: Status };

export type Action =
  | { type: "scan:start" }
  | { type: "scan:done"; found: Incoming[] }
  | { type: "scan:failed"; message: string }
  | { type: "document:changed" }
  | { type: "decide"; id: string; status: Status; note?: string };

export function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "scan:start":
      return { ...state, scanning: true, error: undefined };

    case "scan:failed":
      return { ...state, scanning: false, error: action.message };

    case "scan:done": {
      const batch = state.batch + 1;
      const known = new Set(state.candidates.map((item) => item.key));
      // Only what is new: a re-scan returns everything still in the document,
      // including answered rows — adding them again would duplicate and reset.
      const fresh = action.found
        .filter((item) => !known.has(item.key))
        .map<Candidate>((item) => ({ ...item, status: item.status ?? "pending", batch }));

      // Anything gone from the document is dropped, unless already answered — a
      // decision is a record and outlives the text.
      const still = new Set(action.found.map((item) => item.key));
      const kept = state.candidates.filter(
        (item) => still.has(item.key) || item.status !== "pending",
      );

      return {
        ...state,
        batch,
        scanning: false,
        scanned: true,
        stale: false,
        // Only rows still needing an answer. After a reload the service returns
        // the whole session; flagging decided rows as "new" would scroll to work
        // already done.
        newest: fresh.filter((item) => item.status === "pending").map((item) => item.id),
        candidates: [...fresh, ...kept],
        error: undefined,
      };
    }

    case "document:changed":
      // Cheap and unconditional: comparing text to decide if the change
      // "mattered" is a guess about a document we haven't read since it changed.
      return { ...state, stale: true };

    case "decide":
      return {
        ...state,
        candidates: state.candidates.map((item) =>
          item.id === action.id ? { ...item, status: action.status, note: action.note } : item,
        ),
      };
  }
}

/** The list as the pane draws it: newest batch first, document order within. */
export function ordered(state: State): Candidate[] {
  return [...state.candidates].sort(
    (left, right) =>
      right.batch - left.batch ||
      left.chunk_id.localeCompare(right.chunk_id) ||
      left.char_start - right.char_start,
  );
}

export function counts(state: State) {
  const by = (status: Status) => state.candidates.filter((item) => item.status === status).length;
  return {
    total: state.candidates.length,
    pending: by("pending"),
    redacted: by("applied"),
    dismissed: by("dismissed"),
    failed: by("failed"),
  };
}

/** What the scan button says — one place, because the label IS the state. "Check
 * for new" after a scan, not "Scan", because a reviewer who typed one sentence is
 * not starting from nothing. */
export function scanLabel(state: State): string {
  if (state.scanning) return "Scanning…";
  if (!state.scanned) return "Scan document";
  if (state.stale) return "Check for new";
  return "Re-scan";
}

export function canScan(state: State): boolean {
  return !state.scanning;
}

/** Why this row cannot be put back, or `null` when it can.
 *
 * Redaction is lossy: two different names both become `[NAME REDACTED]`, and
 * nothing then says which marker came from which. Writing one candidate's text
 * over every hit would put Margaret's name where Dmitri's was. So a redaction is
 * reversible only when no other applied row shares its marker in the same part;
 * otherwise the pane refuses and Word's own Undo is still there.
 */
export function revertBlocker(state: State, candidate: Candidate): string | null {
  if (candidate.status === "pending") return "nothing to undo";

  // Nothing was written for these two, so putting the row back is free.
  if (candidate.status === "dismissed" || candidate.status === "failed") return null;

  if (candidate.part_type === "tracked_del") {
    // Removed by accepting the tracked change — Word has no un-accept, and
    // pretending otherwise would say "restored" over text that is gone.
    return "removed by accepting a tracked change — Word cannot un-accept it";
  }

  const sharing = state.candidates.filter(
    (other) =>
      other.id !== candidate.id &&
      other.status === "applied" &&
      other.part_type === candidate.part_type &&
      other.marker === candidate.marker,
  );
  if (sharing.length > 0) {
    return (
      `another redaction in the ${candidate.part_type.replace(/_/g, " ")} also reads ` +
      `${candidate.marker} — which one is which can no longer be told apart`
    );
  }
  return null;
}

export const CATEGORY_LABEL: Record<string, string> = {
  privileged: "Privileged",
  personal: "Personal data",
  health: "Health data",
  account: "Account identifiers",
};
