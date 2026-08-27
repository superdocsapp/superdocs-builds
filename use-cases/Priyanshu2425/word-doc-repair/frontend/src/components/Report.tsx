import type { Capabilities, Report as ReportT } from "../lib/repair";

/** What came through, built only from fields the payload actually carries.
 *  No count is invented: a field that is zero or false says nothing rather
 *  than being padded into a sentence. */
function whatCameThrough(report: ReportT): string[] {
  const lines: string[] = [];
  if (report.word_count > 0) {
    lines.push(
      `${report.word_count} word${report.word_count === 1 ? "" : "s"} of your text`,
    );
  }
  if (report.structure_preserved) {
    // Not "and formatting". `structure_preserved` means the body parsed, and
    // the rebuild then writes clean styles of its own -- so formatting is
    // precisely the thing that may not have survived. Claiming it came
    // through would be a small overclaim in the one place this page exists
    // to be exact about.
    lines.push("the document's structure — its headings and paragraphs");
  }
  if (report.tables_recovered > 0) {
    lines.push(
      `${report.tables_recovered} table${report.tables_recovered === 1 ? "" : "s"}`,
    );
  }
  if (report.images_recovered > 0) {
    const plural = report.images_recovered === 1 ? "" : "s";
    if (report.images_unplaced > 0) {
      // B10: honest, not silent -- recovered, but its position could not be,
      // so it was set at the end rather than guessed at.
      const unplacedPlural = report.images_unplaced === 1 ? "" : "s";
      lines.push(
        `${report.images_recovered} picture${plural}, ${report.images_unplaced} of them ` +
          `set at the end because ${report.images_unplaced === 1 ? "its" : "their"} original position${unplacedPlural} could not be recovered`,
      );
    } else {
      lines.push(`${report.images_recovered} picture${plural}`);
    }
  }
  return lines;
}

/**
 * What happened, in the order a frightened person needs it: the verdict first,
 * then the word count, then what came through and what did not, then the file.
 *
 * A failed recovery renders no download, no "what came through", and no
 * counter door -- a total failure that still offered any of those would be
 * the precise overclaim this build does not make (BUG-012).
 */
export function Report({
  report,
  capabilities,
  onAnother,
  onOpenCounter,
}: {
  report: ReportT;
  capabilities: Capabilities;
  onAnother: () => void;
  onOpenCounter: () => void;
}) {
  const stamp =
    report.verdict === "refused"
      ? "Could not be repaired"
      : report.verdict === "partial"
        ? "Recovered in part"
        : "Recovered";

  return (
    <section aria-labelledby="verdict-h">
      <h2 id="verdict-h" className="sr-only">
        What happened to your document
      </h2>
      <p style={{ margin: "6px 0 0" }}>
        <span
          className={`stamp${report.verdict === "refused" ? " stamp--failed" : report.verdict === "partial" ? " stamp--part" : ""}`}
        >
          {stamp}
        </span>
      </p>

      <p className="verdict">
        {report.verdict === "refused"
          ? "This file could not be repaired. Nothing was invented to fill the gap — if there is another copy, even an older one, that is the better starting point."
          : `Recovered ${report.word_count} word${report.word_count === 1 ? "" : "s"} from your document. This is a best-effort recovery, not a complete repair${
              report.method === "regex"
                ? " — the document's structure was too damaged to read, so the text was recovered run by run."
                : "."
            }`}
      </p>

      {report.ok && whatCameThrough(report).length > 0 ? (
        <div className="outcome outcome--kept">
          <h3 className="outcome__head">What came through</h3>
          <ul className="outcome__list outcome--kept">
            {whatCameThrough(report).map((line) => (
              <li key={line}>
                <i aria-hidden="true">✓</i>
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.lost.length > 0 ? (
        <div className="outcome outcome--lost">
          <h3 className="outcome__head">
            {report.ok ? "What did not come through" : "What went wrong"}
          </h3>
          <ul className="outcome__list outcome--lost">
            {report.lost.map((line) => (
              <li key={line}>
                <i aria-hidden="true">×</i>
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.ok && report.download ? (
        <div className="handoff">
          <div className="tape" />
          <div className="handoff__body">
            <a className="btn" href={report.download} download>
              Download the repaired file
            </a>
            <p className="keep">
              {/* The name, never the path. Each recovery now writes into a
                  directory of its own so two of them cannot collide, which
                  turned `local_rebuild.docx` into a long absolute path
                  through a temporary folder — and put it on screen, where it
                  is noise to the one person who has no use for it. The
                  engine keeps the real path; the page says what the file is
                  called. */}
              Saved as <b>{report.output_path.split("/").pop()}</b>. You can download it more than once. Your original was never changed.
            </p>
            <p className="keep">
              This copy is held for about thirty minutes so you can come back for it, then it is let go.
            </p>

            {/* Styling is part of the recovery, so there is nothing to ask for
                here — only something to say. On the way through it either
                happened or it did not, and the person is told which. Offering
                the plain copy costs a line and saves a second run. */}
            {report.styled ? (
              <p className="keep">
                Styled through SuperDocs, which changed how your words are set and not
                what they say.{" "}
                {report.plain_download ? (
                  <a href={report.plain_download} download>
                    Download the unstyled copy instead
                  </a>
                ) : null}
              </p>
            ) : report.styling_note ? (
              <p className="keep">{report.styling_note}</p>
            ) : null}

            {/* The counter's entry point (PRD §1). The copy is normative: it
                must say the file is already styled, or it reintroduces the
                opt-in button removed 2026-08-26 and makes B3 false. Withheld
                entirely -- never drawn as a button that cannot be pressed --
                when this copy of the page cannot style, per
                GET /api/capabilities. */}
            {capabilities.styling ? (
              <div className="door">
                <button type="button" className="btn btn--quiet" onClick={onOpenCounter}>
                  Set it your way →
                </button>
                {/* The door has to say what a person can actually do here,
                    not just that something is possible. It must also not read
                    as an offer to style the document -- that already happened
                    on the way through, and an invitation to start it would be
                    the opt-in B3 removed. So: it is already styled, and this
                    is where you shape it further.

                    The last sentence is the promise this build is built on
                    (B27): SuperDocs sets how the words look, and only the
                    person changes the words themselves. */}
                <p className="keep">
                  It has been set once already. Carry on in your own words and
                  SuperDocs will shape it however you need — smaller headings,
                  tighter spacing, lighter table rules, the pictures moved.
                  It changes how your words look; only you change the words.
                </p>
              </div>
            ) : (
              <p className="shut">
                {capabilities.note ||
                  "Setting it your way is not available on this copy of the page."}
              </p>
            )}
          </div>
        </div>
      ) : null}

      <div className="after">
        <button type="button" className="btn--quiet btn" onClick={onAnother}>
          Repair another document
        </button>
      </div>
    </section>
  );
}
