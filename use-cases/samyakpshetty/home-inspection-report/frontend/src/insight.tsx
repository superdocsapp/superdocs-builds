/**
 * The two pieces of information design this interface actually needed.
 *
 * Everything else here renders data. These two make it legible:
 *
 * `ReportShape` answers the question anyone picking up an inspection asks first — where are
 * the problems, and how serious — which a scrolling list cannot answer at all. Systems down
 * the side, severity across, count in the cell. Same data as the list, arranged so a
 * property has a shape.
 *
 * `Flagged` marks the rail's objection inside the sentence it objects to, rather than
 * quoting it in a list underneath and making the reader go find it. When the point of a
 * screen is "should these words go in a document", showing which words is the whole job.
 */

import type { Breach, Finding, Severity, System } from "./api";

/* ------------------------------------------------------------------ shape */

export function ReportShape({
  systems,
  severities,
  findings,
}: {
  systems: System[];
  severities: Severity[];
  findings: Finding[];
}) {
  const count = (systemKey: string, severityKey: string) =>
    findings.filter((f) => f.system_key === systemKey && f.severity_key === severityKey).length;

  const total = findings.length;

  return (
    <div className="card stack">
      <div className="section-head">
        <h3>Where the findings are</h3>
        <span className="section-head__count">
          {total === 0
            ? "nothing recorded yet"
            : `${total} across ${new Set(findings.map((f) => f.system_key)).size} systems`}
        </span>
      </div>

      <div className="shape" role="table" aria-label="Findings by system and severity">
        <div className="shape__row shape__head" role="row">
          <span className="shape__label" role="columnheader">
            System
          </span>
          {severities.map((s) => (
            <abbr
              key={s.key}
              className={`shape__cell shape__cell--${s.key}`}
              role="columnheader"
              title={s.label}
              style={{ background: "transparent", color: "var(--ink-faint)" }}
            >
              {/* Two letters, because five full labels across a phone is unreadable. The
                  full label is on the abbr, so it is available to a screen reader and to
                  anyone who hovers. */}
              {initials(s.label)}
            </abbr>
          ))}
        </div>

        {systems.map((system) => {
          const rowTotal = findings.filter((f) => f.system_key === system.key).length;
          return (
            <div className="shape__row" key={system.key} role="row">
              <span className="shape__label" role="rowheader">
                {system.name}
              </span>
              {severities.map((s) => {
                const n = count(system.key, s.key);
                return (
                  <span
                    key={s.key}
                    role="cell"
                    className={[
                      "shape__cell",
                      `shape__cell--${s.key}`,
                      n > 0 ? "shape__cell--has" : rowTotal === 0 ? "shape__cell--clear" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    title={`${system.name} — ${s.label}: ${n}`}
                  >
                    {/* An empty cell says nothing rather than "0", which would read as a
                        finding of zero severity rather than an absence. */}
                    {n > 0 ? n : ""}
                    <span className="visually-hidden">
                      {system.name}, {s.label}: {n}
                    </span>
                  </span>
                );
              })}
            </div>
          );
        })}
      </div>
      <p className="hint">
        An empty row means nothing was observed in that system in the areas inspected — not
        that it was skipped.
      </p>
    </div>
  );
}

// Function words carry no meaning in a two-letter abbreviation: taking the last two words of
// "Noted for the record" gives TR, which stands for nothing. Skipping them gives NR.
const FUNCTION_WORDS = new Set(["for", "the", "a", "an", "of", "to", "and", "in", "on"]);

function initials(label: string): string {
  const words = label
    .split(/\s+/)
    .filter(Boolean)
    .filter((w) => !FUNCTION_WORDS.has(w.toLowerCase()));
  if (words.length === 0) return label.slice(0, 2).toUpperCase();
  if (words.length === 1) return (words[0] ?? "").slice(0, 2).toUpperCase();
  // The last two carry the distinguishing sense: "Recommend prompt evaluation" -> PE,
  // "Recommend maintenance" -> RM, "Noted ... record" -> NR.
  return words
    .slice(-2)
    .map((w) => (w[0] ?? "").toUpperCase())
    .join("");
}

/* ---------------------------------------------------------------- flagged */

/**
 * The proposed sentence with every phrase the rail objected to marked in place.
 *
 * Matching is on the literal text the rail reported, which is the substring it actually
 * matched — so this cannot highlight something the rail did not object to, and cannot miss
 * one it did.
 */
export function Flagged({ text, breaches }: { text: string; breaches: Breach[] }) {
  if (breaches.length === 0) return <>{text}</>;

  const spans: Array<{ start: number; end: number; why: string }> = [];
  for (const b of breaches) {
    if (!b.matched) continue;
    let from = 0;
    for (;;) {
      const at = text.toLowerCase().indexOf(b.matched.toLowerCase(), from);
      if (at < 0) break;
      spans.push({ start: at, end: at + b.matched.length, why: `${b.why} ${b.suggest}` });
      from = at + b.matched.length;
    }
  }
  if (spans.length === 0) return <>{text}</>;

  // Overlapping matches would otherwise render nested marks and duplicate text.
  spans.sort((a, b) => a.start - b.start);
  const merged: typeof spans = [];
  for (const s of spans) {
    const last = merged[merged.length - 1];
    if (last && s.start < last.end) last.end = Math.max(last.end, s.end);
    else merged.push({ ...s });
  }

  const out: React.ReactNode[] = [];
  let cursor = 0;
  merged.forEach((s, i) => {
    if (s.start > cursor) out.push(text.slice(cursor, s.start));
    out.push(
      <mark className="flag" key={i} title={s.why}>
        {text.slice(s.start, s.end)}
      </mark>,
    );
    cursor = s.end;
  });
  if (cursor < text.length) out.push(text.slice(cursor));
  return <>{out}</>;
}

/* ------------------------------------------------------------ word diff */

/** What actually changed between the inspector's words and the proposal. */
export function WordDiff({ before, after }: { before: string; after: string }) {
  const a = before.split(/(\s+)/);
  const b = after.split(/(\s+)/);
  const seen = new Set(a.map((w) => w.toLowerCase().replace(/[^a-z0-9]/g, "")).filter(Boolean));
  return (
    <span className="wdiff">
      {b.map((word, i) => {
        const key = word.toLowerCase().replace(/[^a-z0-9]/g, "");
        if (!key || seen.has(key)) return <span key={i}>{word}</span>;
        return <ins key={i}>{word}</ins>;
      })}
    </span>
  );
}
