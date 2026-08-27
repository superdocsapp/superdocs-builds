import { useCallback, useEffect, useState } from "react";
import {
  RepairError,
  openCounter,
  revertTurn,
  sendTurn,
  styleToken,
  type Receipt,
  type Report as ReportT,
  type Stage,
} from "../lib/repair";
import { Preview } from "./Preview";

/**
 * "Set it your way" — the counter. DESIGN.md: no transcript, one field, one
 * sentence back, receipts one ruled line each, newest first. The width that a
 * transcript would have taken goes to the document instead (V5, chosen shape;
 * docs/style-it-yourself/v5-quiet-counter.html).
 *
 * The session lives here and nowhere else: leaving this screen (`onBack`)
 * does not close it, so coming back finds the same receipts and the same
 * document, not a fresh conversation.
 */

/** Everything about the conversation that a turn, a revert, or reopening the
 *  session can all update in one shot. Kept as one object because the five
 *  endpoints hand these fields back together, never piecemeal. */
interface SessionView {
  turnsLeft: number | null;
  turnsCap: number | null;
  receipts: Receipt[];
  download: string | null;
  plainDownload: string | null;
  authoredWords: number;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** The newest receipt. Receipts arrive oldest-first (each turn appends to the
 *  session's own history), so the newest is the last element -- this is the
 *  one place that ordering assumption lives. */
function newest(receipts: Receipt[]): Receipt | null {
  return receipts.length ? receipts[receipts.length - 1] : null;
}

/** One receipt, as a line. The note is the server's and says what happened;
 *  this adds a label and nothing else. Nothing on this screen says what a
 *  change cost us to make — the person arrived with a broken file, not an
 *  account. */
function entryCopy(r: Receipt): { label: string | null; body: string } {
  // The note is the server's, verbatim -- every degraded outcome states its
  // own reason in one sentence (B21). The label is all this adds.
  if (r.applied) return { label: null, body: r.note };
  return { label: "Not applied", body: r.note };
}

export function Counter({
  report,
  handed,
  onBack,
}: {
  report: ReportT;
  handed: { name: string; size: number };
  onBack: () => void;
}) {
  const token = styleToken(report);

  const [session, setSession] = useState<SessionView | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [stages, setStages] = useState<Stage[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [reverting, setReverting] = useState(false);

  const [side, setSide] = useState<"before" | "after">("after");
  // The current sheet, rendered server-side on the same path the recovery's
  // own preview uses (TurnResult.preview_html). Null means "no turn has
  // changed anything since the original rebuild" -- the toggle then falls
  // back to `report.preview_html` rather than show a blank sheet.
  const [afterHtml, setAfterHtml] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setOpenError("This document does not have a counter to open.");
      return;
    }
    let cancelled = false;
    openCounter(token)
      .then((open) => {
        if (cancelled) return;
        setSession({
          turnsLeft: open.turns_left,
          turnsCap: open.turns_cap,
          receipts: open.receipts,
          download: report.download,
          plainDownload: report.plain_download,
          authoredWords: 0,
        });
      })
      .catch((e) => {
        if (cancelled) return;
        setOpenError(
          e instanceof RepairError
            ? e.message
            : "The counter could not be reached just now. Your document is unchanged.",
        );
      });
    return () => {
      cancelled = true;
    };
    // Opens once per document; `report`/`token` do not change under this screen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const send = useCallback(async () => {
    if (!token || sending || !message.trim()) return;
    const text = message.trim();
    setSending(true);
    setStages([]);
    setProblem(null);
    try {
      const result = await sendTurn(token, text, (s) => setStages((prev) => [...prev, s]));
      setSession({
        turnsLeft: result.turns_left,
        turnsCap: result.turns_cap,
        receipts: result.receipts,
        download: result.download,
        plainDownload: result.plain_download,
        authoredWords: result.authored_words,
      });
      setMessage("");
      // Empty when the export could not be rendered -- an unreadable preview
      // costs the toggle, not the change, so the sheet just stays on
      // whatever it was already showing rather than going blank.
      if (result.preview_html) setAfterHtml(result.preview_html);
      setSide("after");
    } catch (e) {
      setProblem(
        e instanceof RepairError
          ? e.message
          : "Something went wrong before that change could be sent. Nothing was changed.",
      );
    } finally {
      setSending(false);
      setStages([]);
    }
  }, [token, sending, message]);

  const putItBack = useCallback(async () => {
    if (!token || reverting || sending) return;
    setReverting(true);
    setProblem(null);
    try {
      const result = await revertTurn(token);
      setSession({
        turnsLeft: result.turns_left,
        turnsCap: result.turns_cap,
        receipts: result.receipts,
        download: report.download,
        plainDownload: report.plain_download,
        authoredWords: session?.authoredWords ?? 0,
      });
      setMessage(result.compose_text ?? "");
      // Non-empty -- the version reverted onto still has a turn's changes on
      // it -- show it; empty -- the revert landed back on the original
      // rebuild -- fall back to `report.preview_html`, the "as it came back"
      // side. Either way the sheet must agree with what was just put back.
      setAfterHtml(result.preview_html || null);
      setSide("after");
    } catch (e) {
      setProblem(
        e instanceof RepairError
          ? e.message
          : "That could not be put back just now. Nothing else was changed.",
      );
    } finally {
      setReverting(false);
    }
  }, [token, reverting, sending, report.download, report.plain_download, session]);

  const lastReceipt = session ? newest(session.receipts) : null;
  const said = lastReceipt
    ? entryCopy(lastReceipt).body
    // Before the first turn there is no reply to show, and this slot must not
    // echo the heading two lines above it — they were ending on the same
    // clause, so the rail opened by saying the same thing twice. What belongs
    // here instead is the true state of the document.
    : "Nothing asked for yet. Below is the document exactly as it came back.";
  const saidRefused = lastReceipt ? !lastReceipt.applied : false;

  return (
    <div className="counter">
      <div className="tape" />
      <header className="counter__bar">
        <p className="record">
          <span>
            file <b>{handed.name}</b>
          </span>
          <span>
            size{" "}
            <b>
              {handed.size < 1024
                ? `${handed.size} bytes`
                : handed.size < 1024 * 1024
                  ? `${Math.round(handed.size / 1024)} KB`
                  : `${(handed.size / (1024 * 1024)).toFixed(1)} MB`}
            </b>
          </span>
        </p>
        <div className="counter__acts">
          <button type="button" className="btn btn--quiet" onClick={onBack}>
            Back to the report
          </button>
          {session?.plainDownload ? (
            <a className="btn btn--quiet" href={session.plainDownload} download>
              The unstyled copy
            </a>
          ) : null}
          {session?.download ? (
            <a className="btn" href={session.download} download>
              Download the styled file
            </a>
          ) : null}
        </div>
      </header>

      {openError ? (
        <p className="shut" style={{ margin: "20px 24px" }}>
          {openError}
        </p>
      ) : !session ? (
        <p className="working" style={{ margin: "20px 24px" }}>
          <span>Opening the counter</span>
          <span className="working__bar" aria-hidden="true" />
        </p>
      ) : (
        <div className="counter__split">
          <section className="counter__pane">
            <div className="counter__head">
              {/* No "the file itself, not a description of it" here either.
                  The toggle beside this heading already says what the two
                  sides are, and the sheet below is plainly the document. */}
              <h2>The repaired document</h2>
              <div className="two">
                <button
                  type="button"
                  aria-pressed={side === "before"}
                  onClick={() => setSide("before")}
                >
                  As it came back
                </button>
                <button
                  type="button"
                  aria-pressed={side === "after"}
                  onClick={() => setSide("after")}
                >
                  With your changes
                </button>
              </div>
            </div>

            {session.authoredWords > 0 ? (
              <p className="keep" style={{ padding: "0 24px" }}>
                {plural(session.authoredWords, "word")} in this file were written by you here,
                not recovered from your document.
              </p>
            ) : null}

            <div className="counter__scroll">
              <div className="counter__sheet">
                <Preview
                  html={side === "before" ? report.preview_html : (afterHtml ?? report.preview_html)}
                />
              </div>
            </div>
          </section>

          <aside className="rail">
            <div className="rail__head">
              <h2>Set it your way</h2>
              <p>Say what you want changed. The document answers; nobody makes a speech about it.</p>
            </div>

            <div className={`said${saidRefused ? " said--refused" : ""}`}>
              <p className="said__lead">{said}</p>
              {lastReceipt && lastReceipt.applied ? (
                <p className="said__meta">
                  <i aria-hidden="true" />
                  Change {lastReceipt.turn_index} ·{" "}
                  <a
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      void putItBack();
                    }}
                    aria-disabled={reverting || sending}
                  >
                    put it back
                  </a>
                </p>
              ) : null}
            </div>

            <div className="ledger">
              <h3>What you have asked for</h3>
              {[...session.receipts].reverse().map((r, i) => {
                const { label, body } = entryCopy(r);
                return (
                  <div
                    className={`entry${r.applied ? "" : " entry--refused"}`}
                    key={`${r.turn_index}-${i}`}
                  >
                    <i aria-hidden="true" />
                    <span>
                      {label ? <b>{label}</b> : null}
                      {label ? " — " : ""}
                      {body}
                    </span>
                    <time>{r.applied ? r.turn_index : "—"}</time>
                  </div>
                );
              })}

              {session.receipts.length > 0 ? (
                <details className="full">
                  <summary>Read what was said, in full</summary>
                  {session.receipts.map((r, i) => (
                    <div key={`full-${r.turn_index}-${i}`}>
                      <div className="turn turn--you">
                        <span className="who">You</span>
                        <div className="says">{r.asked}</div>
                      </div>
                      <div className="turn">
                        <span className="who">Reply</span>
                        <div className="says">{r.note}</div>
                      </div>
                    </div>
                  ))}
                </details>
              ) : null}
            </div>

            {sending ? (
              <p className="working" style={{ margin: "0 18px 10px" }}>
                <span>{stages[stages.length - 1]?.message ?? "Sending"}</span>
                <span className="working__bar" aria-hidden="true" />
              </p>
            ) : null}

            {problem ? (
              <p className="problem" role="alert" style={{ margin: "0 18px 10px" }}>
                {problem}
              </p>
            ) : null}

            {session.turnsLeft !== null && session.turnsLeft <= 0 ? (
              <p className="shut" style={{ padding: "13px 18px" }}>
                That is the tenth change on this document, which is as many as one recovery
                carries.
              </p>
            ) : (
              <div className="ask">
                <div className="field">
                  <textarea
                    placeholder="What should be different?"
                    value={message}
                    disabled={sending}
                    onChange={(e) => setMessage(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void send();
                      }
                    }}
                  />
                  <button
                    className="send"
                    type="button"
                    disabled={sending || !message.trim()}
                    onClick={() => void send()}
                  >
                    Send
                  </button>
                </div>
                <p className="left-today">
                  <i aria-hidden="true" />
                  <span>
                    <b>
                      {session.turnsLeft === null
                        ? "Checking how many changes are left…"
                        : `${plural(session.turnsLeft, "change")} left on this document.`}
                    </b>{" "}
                    {/* Nothing here about what a change costs us. The person
                        arrived with a broken file, not an account, and a
                        number describing our metering is not one they can
                        act on. The count that is theirs — how many changes
                        this document has left — stays. */}
                    SuperDocs is on the line, holding this document. It
                    changes how your words look; only you change the words.
                  </span>
                </p>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
