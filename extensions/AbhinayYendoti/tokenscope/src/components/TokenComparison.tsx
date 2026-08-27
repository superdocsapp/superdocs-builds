import type { Comparison, Measurement, TokenCount } from "../../shared/types.js";

/**
 * The comparison. This is the product.
 *
 * Two numbers next to each other are only worth showing if the reader can tell
 * which of them was observed and which was worked out, so every figure carries
 * its provenance badge, and the badge is not decorative: an estimate says so, in
 * the same size type as the number.
 *
 * Two comparisons are shown, not one. "What it cost" is SuperDocs' own reported
 * figure, which is the real answer where it exists but is not always reported.
 * "What had to be written" is counted from the text each job returned, is
 * available on every job, and is the one that behaves predictably as documents
 * get large.
 */

const BADGES: Record<TokenCount["source"], { label: string; title: string }> = {
  measured: {
    label: "Measured",
    title: "Reported by SuperDocs for a job it actually ran. Not computed by TokenScope."
  },
  tokenized: {
    label: "Tokenized",
    title: "Counted from text that really exists, with a real BPE tokenizer, locally."
  },
  estimated: {
    label: "Estimated",
    title: "Derived from measured and tokenized values. Not an observed cost."
  }
};

function Badge({ source }: { source: TokenCount["source"] }): JSX.Element {
  const badge = BADGES[source];

  return (
    <span className={`badge badge--${source}`} title={badge.title}>
      {badge.label}
    </span>
  );
}

function format(value: number): string {
  return value.toLocaleString("en-US");
}

function Figure({
  label,
  count,
  tone
}: {
  label: string;
  count: TokenCount | null;
  tone: "surgical" | "whole";
}): JSX.Element {
  return (
    <div className={`figure figure--${tone}`}>
      <div className="figure__label">{label}</div>

      {count === null ? (
        <>
          <div className="figure__value figure__value--absent">Not reported</div>
          <p className="figure__method">
            SuperDocs returned no token count for this job. TokenScope will not put a number here
            that it made up.
          </p>
        </>
      ) : (
        <>
          <div className="figure__value">{format(count.tokens)}</div>
          <div className="figure__unit">tokens</div>
          <Badge source={count.source} />
          <p className="figure__method">{count.method}</p>
        </>
      )}
    </div>
  );
}

function ComparisonBlock({ comparison }: { comparison: Comparison }): JSX.Element {
  const { savings } = comparison;
  const cheaper = savings !== null && savings.tokens > 0;

  return (
    <section className="comparison" aria-label={comparison.label}>
      <h3 className="comparison__label">{comparison.label}</h3>

      <div className="comparison__pair">
        <Figure label="Surgical edit" count={comparison.surgical} tone="surgical" />
        <Figure label="Whole document" count={comparison.wholeDocument} tone="whole" />
      </div>

      {savings === null ? (
        <p className="comparison__no-savings">No comparison is possible without both numbers.</p>
      ) : (
        <div className={`savings ${cheaper ? "savings--positive" : "savings--negative"}`}>
          <div className="savings__ratio">
            {cheaper ? "" : "+"}
            {(Math.abs(savings.ratio) * 100).toFixed(2)}%
          </div>
          <div className="savings__caption">
            {cheaper ? (
              <>
                saved by editing the selection instead of the document
                <span className="savings__delta">{format(savings.tokens)} tokens not spent</span>
              </>
            ) : (
              <>
                more than regenerating this document
                <span className="savings__delta">
                  At this size the agent&rsquo;s fixed overhead dominates. The gap turns over as the
                  document grows &mdash; see the benchmark.
                </span>
              </>
            )}
          </div>
        </div>
      )}

      <p className="comparison__note">{comparison.note}</p>
    </section>
  );
}

export function TokenComparison({
  measurement,
  onMeasureWholeDocument,
  measuring
}: {
  measurement: Measurement;
  onMeasureWholeDocument: () => void;
  measuring: boolean;
}): JSX.Element {
  const { reported, written, sections, selection, document } = measurement;
  const notMeasuredYet = written.wholeDocument?.source === "estimated";

  return (
    <div className="comparisons">
      <ComparisonBlock comparison={reported} />
      <ComparisonBlock comparison={written} />

      <dl className="context">
        <div>
          <dt>Sections changed</dt>
          <dd>
            {sections.surgical} vs{" "}
            {sections.wholeDocument === null ? "not measured" : sections.wholeDocument}
          </dd>
        </div>
        <div>
          <dt>Selected text</dt>
          <dd>
            {format(selection.tokens)} tokens <Badge source={selection.source} />
          </dd>
        </div>
        <div>
          <dt>Document body</dt>
          <dd>
            {format(document.tokens)} tokens <Badge source={document.source} />
          </dd>
        </div>
      </dl>

      {notMeasuredYet && (
        <div className="comparison__upgrade">
          <p>
            The whole-document column is still an estimate. TokenScope can measure it instead, by
            running the regeneration for real in a throwaway session. Your document is not touched
            and nothing it proposes is applied.
          </p>
          <button type="button" onClick={onMeasureWholeDocument} disabled={measuring}>
            {measuring ? "Regenerating the whole document…" : "Measure it for real"}
          </button>
          <span className="comparison__cost">
            Costs one SuperDocs operation. Slow on large documents.
          </span>
        </div>
      )}
    </div>
  );
}
