import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { type Host, detectHost } from "./office";
import {
  CATEGORY_LABEL,
  type Candidate,
  canScan,
  counts,
  initial,
  ordered,
  reduce,
  revertBlocker,
  scanLabel,
} from "./session";

/** The pane. A Word task pane is ~320px wide, so this reads as a narrow column:
 * header, a scrolling list of findings, one action bar pinned at the bottom.
 *
 * Nothing is removed without a click on a row — there is no "redact everything"
 * that skips the list.
 *
 * See extensions/redaction-pane/README.md § "The API, and what it cannot do".
 */
export function App() {
  const [state, dispatch] = useReducer(reduce, initial);
  const [host, setHost] = useState<Host | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [scanInfo, setScanInfo] = useState<ScanInfo | null>(null);
  const [session, setSession] = useState("");
  const [documentHash, setDocumentHash] = useState("");
  const [reviewer, setReviewer] = useState(() => localStorage.getItem(REVIEWER_KEY) ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  /** The footer's result message. `kind` drives the colour, so a failure is
   * never mistaken for a success at a glance. */
  const [banner, setBanner] = useState<{ kind: "ok" | "bad" | "busy"; text: string } | null>(null);
  /** Which footer actions are running. A set, not one slot: exporting takes
   * seconds against SuperDocs, and each action blocks only itself so a reviewer
   * can keep working the list while one runs. */
  const [working, setWorking] = useState<Set<"export" | "logs">>(new Set());

  const start = useCallback((job: "export" | "logs") => {
    setWorking((current) => new Set(current).add(job));
  }, []);
  const finish = useCallback((job: "export" | "logs") => {
    setWorking((current) => {
      const next = new Set(current);
      next.delete(job);
      return next;
    });
  }, []);
  const summaryRef = useRef(counts(initial));
  const listRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void detectHost().then(async (found) => {
      setHost(found);
      // Word tells us when the text changes; that is what re-arms the button.
      // No polling, and no guessing whether the change "mattered".
      await found.onDocumentChanged(() => dispatch({ type: "document:changed" }));
    });
    void fetch("/health")
      .then((response) => response.json())
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  // The scroll rule: when a scan adds rows, put the newest one in view. When it
  // adds nothing, leave the reviewer exactly where they were reading.
  useEffect(() => {
    if (state.newest.length === 0) return;
    topRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [state.newest]);

  const nameReviewer = useCallback((value: string) => {
    setReviewer(value);
    // Kept so the next scan is not "unidentified" again — a convenience, not a
    // credential: the log says the name is self-declared.
    localStorage.setItem(REVIEWER_KEY, value);
  }, []);

  const scan = useCallback(async () => {
    if (!host) return;
    dispatch({ type: "scan:start" });
    try {
      const file = await host.getFile();
      const body = new FormData();
      // `.slice()` copies into a plain ArrayBuffer: Word's slices can be backed
      // by a SharedArrayBuffer, which `Blob` rejects — a build-time type error,
      // not a broken upload at runtime.
      body.append("file", new Blob([file.bytes.slice().buffer]), file.filename);
      // Sent so a re-scan continues the same session and audit log, not three.
      body.append("session_id", session);
      body.append("reviewer", reviewer);
      const response = await fetch("/scan", { method: "POST", body });
      if (!response.ok) throw new Error(await detail(response));
      const payload = await response.json();
      setSession(payload.session_id);
      setDocumentHash(payload.document_hash);
      setScanInfo(payload.scan);
      dispatch({ type: "scan:done", found: payload.candidates });
    } catch (error) {
      dispatch({ type: "scan:failed", message: (error as Error).message });
    }
  }, [host, session, reviewer]);

  const decide = useCallback(
    async (candidate: Candidate, confirmed: boolean) => {
      if (!host) return;
      if (!confirmed) {
        dispatch({ type: "decide", id: candidate.id, status: "dismissed" });
        void post(`/candidates/${candidate.id}/dismiss`, { reviewer });
        return;
      }
      setBusy(candidate.id);
      try {
        // Applied through Word in place, one item at a time — the click and the
        // removal are one action, and the service is told AFTERWARDS, so the log
        // only describes a removal that happened. The marker comes from the
        // candidate, so the released document stays readable and an
        // over-redaction is visible rather than hidden behind a uniform marker.
        const result = await host.redact([
          { text: candidate.text, part: candidate.part_type as never, marker: candidate.marker },
        ]);
        const failure = result.failed[0];
        dispatch({
          type: "decide",
          id: candidate.id,
          status: failure ? "failed" : "applied",
          note: failure?.reason ?? result.detail,
        });
        void post(`/candidates/${candidate.id}/redacted`, {
          applied: result.applied,
          failed: result.failed,
          reviewer,
          // What was actually written. Blank when removed by accepting a
          // tracked deletion — no marker entered the document.
          marker: result.detail ? "" : candidate.marker,
          detail: result.detail ?? "",
        });
      } finally {
        setBusy(null);
      }
    },
    [host, reviewer],
  );

  const revert = useCallback(
    async (candidate: Candidate) => {
      if (!host) return;
      setBusy(candidate.id);
      try {
        // Only "applied" wrote anything, so only "applied" needs Word. A
        // dismissal is undone by changing a row.
        if (candidate.status === "applied") {
          const result = await host.restore({
            text: candidate.text,
            part: candidate.part_type as never,
            marker: candidate.marker,
          });
          const failure = result.failed[0];
          if (failure) {
            // Word first, service second. If the text did not go back, the row
            // stays redacted and says why, not pending over missing text.
            dispatch({ type: "decide", id: candidate.id, status: "applied", note: failure.reason });
            return;
          }
        }
        dispatch({ type: "decide", id: candidate.id, status: "pending" });
        void post(`/candidates/${candidate.id}/revert`, { reviewer });
      } finally {
        setBusy(null);
      }
    },
    [host, reviewer],
  );

  const exportClean = useCallback(async () => {
    if (!host || !session) return;
    start("export");
    // The file is a snapshot of now, but the reviewer can keep redacting while
    // it runs — so capture the count to compare against afterwards.
    const confirmedAtStart = summaryRef.current.redacted;
    setBanner({
      kind: "busy",
      text: "Uploading to SuperDocs, redacting the confirmed text, and verifying the result. This takes a few seconds.",
    });
    try {
      // Re-sent, not held server-side: the pane's copy is current, and the
      // service keeps no document bytes.
      const file = await host.getFile();
      const body = new FormData();
      body.append("file", new Blob([file.bytes.slice().buffer]), file.filename);
      body.append("session_id", session);
      const response = await fetch("/export", { method: "POST", body });
      if (!response.ok) throw new Error(await detail(response));
      const payload = await response.json();
      // Never "done" just because a file exists. The clean flag is the
      // verification, and a file that failed it is still written so the reviewer
      // can see what came back.
      setBanner(
        payload.clean
          ? {
              kind: "ok",
              text: `Clean copy saved to ${payload.path} — ${payload.verification?.summary ?? ""}`,
            }
          : {
              kind: "bad",
              text:
                `NOT clean. ${payload.verification?.summary ?? payload.warnings?.join(" ") ?? ""}` +
                (payload.path ? ` The file is at ${payload.path} so you can see what came back.` : ""),
            },
      );
    } catch (error) {
      setBanner({ kind: "bad", text: `Export failed: ${(error as Error).message}` });
    } finally {
      finish("export");
      // Redactions confirmed while the export was in flight are NOT in the file
      // — the service read the list when the request arrived. Said out loud, or
      // the reviewer hands over a copy missing their last few removals.
      setBanner((current) => {
        const since = summaryRef.current.redacted - confirmedAtStart;
        return current && since > 0
          ? {
              ...current,
              text:
                `${current.text} — note: ${since} more redaction(s) were confirmed while this ` +
                "ran and are NOT in that file. Export again to include them.",
            }
          : current;
      });
    }
  }, [host, session, start, finish]);

  const downloadLogs = useCallback(async () => {
    start("logs");
    setBanner({ kind: "busy", text: "Writing the log…" });
    try {
      // Written by the service, not fetched by the pane: a task pane is a
      // sandboxed iframe where `window.open` is blocked and `<a download>` on a
      // blob URL is inert, so a browser-style download fails silently. The
      // service writes to the mounted folder and tells us where.
      const response = await fetch(`/audit/download?document=${encodeURIComponent(documentHash)}`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(await detail(response));
      const payload = await response.json();
      setBanner({ kind: "ok", text: `Saved ${payload.entries} entries to ${payload.path}` });
    } catch (error) {
      setBanner({ kind: "bad", text: `Could not save the log: ${(error as Error).message}` });
    } finally {
      finish("logs");
    }
  }, [documentHash, start, finish]);

  const summary = counts(state);
  const rows = ordered(state);
  // A ref, because the export's `finally` closed over the counts at click time
  // and needs to see the current ones.
  summaryRef.current = summary;

  return (
    <div className="pane">
      <header className="pane__head">
        <div className="pane__title">
          <span>Redaction</span>
          {state.scanned && (
            <span className="pane__counts">
              {summary.pending} to review · {summary.redacted} redacted
            </span>
          )}
        </div>

        {/* "By whom" is a requirement of the log. There is no sign-in here, so
            the pane asks and the log records the answer as self-declared —
            which is the honest version of an unauthenticated name. */}
        <label className="who">
          <span>Reviewing as</span>
          <input
            value={reviewer}
            placeholder="your name — recorded in the log, not verified"
            onChange={(event) => nameReviewer(event.target.value)}
          />
        </label>

        {host && !host.available && (
          <p className="note note--warn">
            Not running inside Word. Sideload the add-in to scan a document — this pane cannot
            read one on its own.
          </p>
        )}
        {health?.degraded && (
          <p className="note">
            {health.missing_configuration.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </p>
        )}
        {/* The box the reviewer asked for. Word tells us the text changed, so
            the pane says the list is out of date rather than letting somebody
            finish a review of a document that has moved on. */}
        {state.stale && (
          <p className="note note--stale">
            <b>You have edited the document.</b> Re-scan before you finish — this
            list describes the text as it was.
          </p>
        )}
      </header>

      <div className="pane__list" ref={listRef}>
        <div ref={topRef} />
        {!state.scanned && !state.scanning && (
          <div className="empty">
            <p>Nothing has been scanned yet.</p>
            <p className="empty__why">
              The scan reads the whole file — body, headers, footers, footnotes, comments and
              the contents of tracked deletions.
            </p>
          </div>
        )}
        {state.error && <p className="note note--warn">{state.error}</p>}
        {scanInfo?.notes.map((note) => (
          <p className="note note--warn" key={note}>
            {note}
          </p>
        ))}
        {state.scanned && rows.length === 0 && (
          <div className="empty">
            <p>Nothing to review.</p>
            {/* The sentence a reviewer needs is not "no candidates" — it is what
                ran. An empty list from a full scan and an empty list from a
                detector that never started look identical, and only one of them
                means the document is clean. */}
            <p className="empty__why">{scanInfo ? whereItLooked(scanInfo) : ""}</p>
          </div>
        )}

        {rows.map((candidate) => (
          <Row
            key={candidate.id}
            candidate={candidate}
            busy={busy === candidate.id}
            isNew={state.newest.includes(candidate.id)}
            blocker={revertBlocker(state, candidate)}
            onDecide={decide}
            onRevert={revert}
          />
        ))}

        {/* Only when there is a list above it. With an empty list the same
            sentence is already the empty state, and printing it twice is how a
            reviewer learns to stop reading this pane. */}
        {state.scanned && scanInfo && rows.length > 0 && (
          <p className="scanned-note">
            {whereItLooked(scanInfo)}
            {/* Not a detail. "The model found nothing" and "the model found
                four things, none of which are in this document" are different
                states, and only one of them means the block is clean. */}
            {scanInfo.dropped_unverifiable > 0 &&
              ` ${scanInfo.dropped_unverifiable} suggestion(s) were dropped: the exact` +
                ` words are not in the document.`}
          </p>
        )}

        {/* Where the file went. The pane never opens a browser, so this line is
            the only thing that tells a reviewer the log exists on disk. */}
        {banner && (
          <div className={`banner banner--${banner.kind}`} role="status" aria-live="polite">
            <span>{banner.text}</span>
            {banner.kind !== "busy" && (
              <button className="banner__close" onClick={() => setBanner(null)} aria-label="Dismiss">
                ×
              </button>
            )}
          </div>
        )}

        {state.scanned && (
          <p className="boundary">
            This pane removes text from the visible document. Document properties and file
            metadata are outside what it removes — they are checked after export and reported.
            Redaction here requires your review; it is not a certificate that a document is
            safe to release.
          </p>
        )}
      </div>

      <footer className="pane__foot">
        <button
          className={`btn btn--primary${state.stale ? " btn--alert" : ""}`}
          onClick={() => void scan()}
          disabled={!canScan(state) || !host}
        >
          {scanLabel(state)}
        </button>
        <button
          className="btn"
          disabled={summary.redacted === 0 || working.has("export")}
          onClick={() => void exportClean()}
          title="Upload to SuperDocs, redact the confirmed strings, and verify the result"
        >
          {working.has("export") ? "Exporting…" : "Clean copy"}
        </button>
        <button
          className="btn"
          disabled={
            summary.redacted + summary.dismissed + summary.failed === 0 || working.has("logs")
          }
          onClick={() => void downloadLogs()}
        >
          {working.has("logs") ? "Saving…" : "Download logs"}
        </button>
      </footer>
    </div>
  );
}

const REVIEWER_KEY = "redaction-pane.reviewer";

const PART_NOUN: Record<string, [string, string]> = {
  body: ["paragraph", "paragraphs"],
  header: ["header", "headers"],
  footer: ["footer", "footers"],
  footnote: ["footnote", "footnotes"],
  endnote: ["endnote", "endnotes"],
  comment: ["comment", "comments"],
  tracked_del: ["tracked deletion", "tracked deletions"],
};

const TIER_NOUN: Record<string, string> = {
  patterns: "pattern matching",
  ner: "the local name model",
  llm: "the language model",
};

/** What the scan looked at, as a sentence a person would say. "Nothing to
 * review" alone is uncheckable; with the parts and detectors beside it, one
 * comment where the document has four means the scan is wrong, not the document. */
function whereItLooked(scan: ScanInfo): string {
  const parts = Object.entries(scan.coverage)
    .map(([part, count]) => {
      const [one, many] = PART_NOUN[part] ?? [part.replace(/_/g, " "), part.replace(/_/g, " ")];
      return `${count} ${count === 1 ? one : many}`;
    })
    .join(", ");
  const tiers = scan.tiers.map((tier) => TIER_NOUN[tier] ?? tier);
  const read = `Read ${parts || "nothing"} using ${list(tiers)}.`;
  // Saying the hidden places were searched matters most when empty. Counting
  // them would claim "0 comments" as a finding; saying nothing leaves a reviewer
  // wondering. This says it looked and found none.
  const onlyBody = Object.keys(scan.coverage).every((part) => part === "body");
  return onlyBody
    ? `${read} This file has no headers, footers, comments or tracked changes to search.`
    : read;
}

/** "a, b and c". A pane that says "patterns, llm" is showing its variable
 * names to a records officer. */
function list(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "nothing";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

async function post(url: string, body: unknown): Promise<void> {
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** FastAPI puts the reason in `detail`. Showing the raw JSON envelope in a
 * 320px pane is how an error message becomes something nobody reads. */
async function detail(response: Response): Promise<string> {
  const text = await response.text();
  try {
    return String(JSON.parse(text).detail ?? text);
  } catch {
    return text;
  }
}

function Row({
  candidate,
  busy,
  isNew,
  blocker,
  onDecide,
  onRevert,
}: {
  candidate: Candidate;
  busy: boolean;
  isNew: boolean;
  /** Why this row cannot be put back, or null. Computed across the whole
   * session, because the answer depends on the other rows. */
  blocker: string | null;
  onDecide: (candidate: Candidate, confirmed: boolean) => void;
  onRevert: (candidate: Candidate) => void;
}) {
  const decided = candidate.status !== "pending";
  return (
    <article className={`row row--${candidate.status}${isNew ? " row--new" : ""}`}>
      <div className="row__head">
        <span className={`tag tag--${candidate.category}`}>
          {CATEGORY_LABEL[candidate.category] ?? candidate.category}
        </span>
        <span className="row__kind">{candidate.kind.replace(/_/g, " ")}</span>
        {/* Where it lives. An identifier inside a tracked deletion is invisible
            in Word, and it is exactly the one a reviewer must be told about. */}
        {candidate.part_type !== "body" && (
          <span className="tag tag--part">{candidate.part_type.replace(/_/g, " ")}</span>
        )}
        <span className="row__detector" title="Which detector found this">
          {candidate.detector}
        </span>
      </div>

      {/* The surrounding sentence, with the candidate marked — "is this
          sensitive?" has no answer without it. */}
      <p className="row__sentence">
        {split(candidate.sentence, candidate.text).map((piece, index) =>
          piece.hit ? (
            <mark key={index}>{piece.text}</mark>
          ) : (
            <span key={index}>{piece.text}</span>
          ),
        )}
      </p>

      {/* What the document will say afterwards. Shown before the click, so
          "Redact" is a decision about a specific replacement rather than a
          leap of faith about what `[REDACTED]` will do to the sentence. */}
      {!decided && <p className="row__marker">becomes {candidate.marker}</p>}

      {decided ? (
        <div className="row__decided">
          <p className="row__state">
            {candidate.status === "applied" && (candidate.note ?? "Redacted")}
            {candidate.status === "dismissed" && "Dismissed — left in the document"}
            {candidate.status === "failed" && `Could not redact: ${candidate.note}`}
          </p>
          {/* A decision should be reversible where reversing it is *correct*.
              Where it is not, the row says so rather than offering a button
              that would put the wrong text back. */}
          {blocker === null ? (
            <button
              className="btn btn--small"
              disabled={busy}
              onClick={() => onRevert(candidate)}
            >
              {busy ? "Undoing…" : "Undo"}
            </button>
          ) : (
            <p className="row__blocker">Cannot undo: {blocker}</p>
          )}
        </div>
      ) : (
        <div className="row__actions">
          <button className="btn btn--small" onClick={() => onDecide(candidate, false)}>
            Dismiss
          </button>
          <button
            className="btn btn--small btn--primary"
            disabled={busy}
            onClick={() => onDecide(candidate, true)}
          >
            {busy ? "Redacting…" : "Redact"}
          </button>
        </div>
      )}
    </article>
  );
}

/** Split a sentence around the candidate so it can be marked in place. */
function split(sentence: string, text: string): { text: string; hit: boolean }[] {
  const at = sentence.indexOf(text);
  if (at === -1) return [{ text: sentence, hit: false }];
  return [
    { text: sentence.slice(0, at), hit: false },
    { text, hit: true },
    { text: sentence.slice(at + text.length), hit: false },
  ].filter((piece) => piece.text.length > 0);
}

interface Health {
  tiers: string[];
  degraded: boolean;
  missing_configuration: string[];
}

/** Only the fields the pane draws. `/scan` returns more — block counts, token
 * usage, new-row counts — for a reviewer reading the API or a test. */
interface ScanInfo {
  coverage: Record<string, number>;
  tiers: string[];
  dropped_unverifiable: number;
  notes: string[];
}
